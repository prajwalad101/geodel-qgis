"""Pure-Python client for the QGIS plugin API."""

from pathlib import Path
from time import monotonic, sleep
from typing import Any, Callable, Dict, List, Optional, Tuple

from .transport import (
    Response, Transport, TransportCanceled, TransportError,
)

from .config import PRODUCT_NAME
from .recent_upload import RecentUpload, project_recent_upload


PART_SIZE = 10 * 1024 * 1024
MAX_FILE_SIZE = 60 * 1024 * 1024
MAX_FILE_SIZE_LABEL = f"{MAX_FILE_SIZE // (1024 * 1024)} MB"
POLL_TIMEOUT_SECONDS = 10 * 60


class GeoDelError(Exception):
    """API request failed."""


class AuthenticationError(GeoDelError):
    """The API rejected the configured key."""


class AuthorizationError(GeoDelError):
    """Access to a resource was denied."""


class ServerUnavailableError(GeoDelError):
    """The API could not be reached or failed server-side."""


class UploadCanceled(GeoDelError):
    """User canceled an upload."""


class GeoDelClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        plugin_version: str,
        transport: Transport,
        is_canceled: Optional[Callable[[], bool]] = None,
    ) -> None:
        base_url = base_url.rstrip("/")
        self.base_url = (
            base_url if base_url.endswith("/api/v1") else f"{base_url}/api/v1"
        )
        self.api_key = api_key
        self.plugin_version = plugin_version
        self.transport = transport
        self.is_canceled = is_canceled

    def list_organizations(self) -> List[Dict[str, Any]]:
        payload = self._get("/organizations")
        organizations = payload.get("organizations")
        if not isinstance(organizations, list) or not all(
            isinstance(org, dict)
            and isinstance(org.get("id"), str)
            and isinstance(org.get("name"), str)
            for org in organizations
        ):
            raise GeoDelError(
                f"{PRODUCT_NAME} returned an invalid workspaces response"
            )
        return organizations

    def get_meta(self) -> Dict[str, Any]:
        payload = self._get("/meta")
        if not isinstance(payload.get("minPluginVersion"), str):
            raise GeoDelError(f"{PRODUCT_NAME} returned invalid plugin metadata")
        return payload

    def requires_update(self) -> bool:
        minimum = self.get_meta()["minPluginVersion"]
        try:
            installed_version = _version_tuple(self.plugin_version)
        except ValueError as error:
            raise GeoDelError("Installed plugin version is invalid") from error
        try:
            minimum_version = _version_tuple(minimum)
        except ValueError as error:
            raise GeoDelError(
                f"{PRODUCT_NAME} returned an invalid minimum plugin version"
            ) from error
        return installed_version < minimum_version

    def list_folders(self, organization_id: str) -> List[Dict[str, Any]]:
        payload = self._get("/folders", organization_id)
        folders = payload.get("folders")
        if not isinstance(folders, list) or not all(
            _valid_folder(folder) for folder in folders
        ):
            raise GeoDelError(f"{PRODUCT_NAME} returned an invalid folders response")
        return folders

    def list_recent_uploads(self, organization_id: str) -> List[RecentUpload]:
        payload = self._get("/uploads", organization_id, params={"recent": "true"})
        uploads = payload.get("uploads")
        if not isinstance(uploads, list):
            raise GeoDelError(f"{PRODUCT_NAME} returned an invalid uploads response")
        try:
            return [project_recent_upload(upload, self.base_url) for upload in uploads]
        except ValueError as error:
            raise GeoDelError(
                f"{PRODUCT_NAME} returned an invalid uploads response"
            ) from error

    def upload_file(
        self,
        path: Path,
        filename: str,
        organization_id: str,
        folder_id: Optional[str] = None,
        progress: Optional[Callable[[float], None]] = None,
        is_canceled: Optional[Callable[[], bool]] = None,
    ) -> str:
        is_canceled = is_canceled or self.is_canceled
        path = Path(path)
        try:
            file_stat = path.stat()
        except OSError as error:
            raise GeoDelError(f"Could not read upload file: {error}") from error
        file_size = file_stat.st_size

        if file_size == 0:
            raise GeoDelError("Upload file is empty")
        if file_size > MAX_FILE_SIZE:
            raise GeoDelError(f"Upload file exceeds the {MAX_FILE_SIZE_LABEL} limit")

        upload_format, content_type = _upload_type(filename)
        if is_canceled and is_canceled():
            raise UploadCanceled("Upload canceled")

        initialized = self._request(
            "POST",
            "/uploads/s3/multipart",
            organization_id,
            is_canceled=is_canceled,
            json={
                "filename": filename,
                "type": content_type,
                "metadata": {
                    "fileSizeKb": (file_size + 1023) // 1024,
                    "lastModified": int(file_stat.st_mtime * 1000),
                    "format": upload_format,
                },
            },
        )
        upload_id = initialized.get("uploadId")
        key = initialized.get("key")
        if not isinstance(upload_id, str) or not isinstance(key, str):
            raise GeoDelError(
                f"{PRODUCT_NAME} returned an invalid multipart response"
            )

        parts = []
        uploaded = 0
        try:
            with path.open("rb") as source:
                for part_number, chunk in enumerate(
                    iter(lambda: source.read(PART_SIZE), b""), 1
                ):
                    if is_canceled and is_canceled():
                        raise UploadCanceled("Upload canceled")
                    signed = self._get(
                        f"/uploads/s3/multipart/{upload_id}/{part_number}",
                        organization_id,
                        params={"key": key},
                        is_canceled=is_canceled,
                    )
                    url = signed.get("url")
                    if not isinstance(url, str):
                        raise GeoDelError(
                            f"{PRODUCT_NAME} returned an invalid part upload URL"
                        )
                    etag = self._put_part(url, chunk, is_canceled)
                    parts.append({"PartNumber": part_number, "ETag": etag})
                    uploaded += len(chunk)
                    if progress:
                        progress(uploaded / file_size * 100)

            self._request(
                "POST",
                f"/uploads/s3/multipart/{upload_id}/complete",
                organization_id,
                params={"key": key},
                json={"parts": parts},
                is_canceled=is_canceled,
            )
            registered = self._request(
                "POST",
                "/uploads/register",
                organization_id,
                is_canceled=is_canceled,
                json={
                    "attemptId": upload_id,
                    **({"folderId": folder_id} if folder_id else {}),
                },
            )
            registered_id = registered.get("id")
            if not isinstance(registered_id, str):
                raise GeoDelError(f"{PRODUCT_NAME} returned an invalid upload response")
        except (GeoDelError, OSError) as error:
            try:
                self._request(
                    "DELETE",
                    f"/uploads/s3/multipart/{upload_id}",
                    organization_id,
                    params={"key": key},
                    is_canceled=lambda: False,
                )
            except GeoDelError:
                pass
            if isinstance(error, GeoDelError):
                raise
            raise GeoDelError(f"Could not read upload file: {error}") from error

        return registered_id

    def publish_file(
        self,
        path: Path,
        filename: str,
        organization_id: str,
        folder_id: Optional[str] = None,
        progress: Optional[Callable[[float], None]] = None,
        is_canceled: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        is_canceled = is_canceled or self.is_canceled
        upload_id = self.upload_file(
            path,
            filename,
            organization_id,
            folder_id,
            (lambda value: progress(value * 0.9)) if progress else None,
            is_canceled,
        )
        started = monotonic()
        delay = 3.0
        status_errors = 0
        share_token_errors = 0
        while monotonic() - started < POLL_TIMEOUT_SECONDS:
            if is_canceled and is_canceled():
                raise UploadCanceled("Upload canceled")
            try:
                status = self.get_upload_status(upload_id, organization_id, is_canceled)
            except (AuthenticationError, AuthorizationError, UploadCanceled):
                raise
            except GeoDelError:
                status_errors += 1
                if status_errors >= 3:
                    raise
                status = None
            if status is not None:
                status_errors = 0
                if status["status"] == "failed":
                    raise GeoDelError(
                        status.get("errorMessage") or "Upload processing failed"
                    )
                if status["status"] == "ready":
                    try:
                        share_token = self.get_share_token(upload_id, organization_id, is_canceled)
                    except (AuthenticationError, AuthorizationError, UploadCanceled):
                        raise
                    except GeoDelError:
                        share_token_errors += 1
                        if share_token_errors >= 3:
                            raise
                    else:
                        if progress:
                            progress(100)
                        return {"shareToken": share_token, "timedOut": False}

            elapsed = monotonic() - started
            if progress:
                progress(min(99, 90 + elapsed / POLL_TIMEOUT_SECONDS * 9))
            wait_until = monotonic() + delay
            while monotonic() < wait_until:
                if is_canceled and is_canceled():
                    raise UploadCanceled("Upload canceled")
                remaining = wait_until - monotonic()
                if remaining <= 0:
                    break
                sleep(min(0.25, remaining))
            delay = min(delay * 1.5, 15)

        return {"timedOut": True}

    def get_upload_status(
        self, upload_id: str, organization_id: str,
        is_canceled: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        payload = self._get(f"/uploads/{upload_id}/status", organization_id, is_canceled=is_canceled)
        if (
            payload.get("id") != upload_id
            or payload.get("status") not in ("pending", "processing", "ready", "failed")
            or payload.get("errorMessage") is not None
            and not isinstance(payload.get("errorMessage"), str)
        ):
            raise GeoDelError(f"{PRODUCT_NAME} returned an invalid upload status")
        return payload

    def get_share_token(
        self, upload_id: str, organization_id: str,
        is_canceled: Optional[Callable[[], bool]] = None,
    ) -> str:
        payload = self._get(f"/uploads/{upload_id}/detail", organization_id, is_canceled=is_canceled)
        token = payload.get("shareToken")
        if not isinstance(token, str):
            raise GeoDelError(f"{PRODUCT_NAME} returned an invalid share link")
        return token

    def _get(
        self,
        path: str,
        organization_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        is_canceled: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        return self._request("GET", path, organization_id, params=params, is_canceled=is_canceled)

    def _request(
        self,
        method: str,
        path: str,
        organization_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        headers = {"X-Plugin-Version": self.plugin_version}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if organization_id:
            headers["X-Organization-Id"] = organization_id

        try:
            response = self.transport.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                timeout=15,
                is_canceled=kwargs.pop("is_canceled", None) or self.is_canceled,
                **{key: value for key, value in kwargs.items() if value is not None},
            )
        except TransportCanceled as error:
            raise UploadCanceled("Upload canceled") from error
        except TransportError as error:
            raise ServerUnavailableError(
                f"{PRODUCT_NAME} request failed: Network, TLS or timeout failure"
            ) from error
        if response.status_code == 401:
            raise AuthenticationError("API key is invalid or revoked")
        if response.status_code == 403:
            raise AuthorizationError("API key does not have access to this resource")
        if response.status_code >= 400 or response.status_code < 200:
            reason = _response_error(response) or f"HTTP {response.status_code}"
            # Service error bodies are untrusted and may echo the submitted key.
            if self.api_key:
                reason = reason.replace(self.api_key, "[redacted]")
            failure = ServerUnavailableError if response.status_code >= 500 else GeoDelError
            raise failure(f"{PRODUCT_NAME} request failed: {reason}")
        try:
            payload = response.json()
        except (ValueError, UnicodeError) as error:
            raise GeoDelError(f"{PRODUCT_NAME} returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise GeoDelError(f"{PRODUCT_NAME} returned an invalid response")
        return payload

    def _put_part(
        self, url: str, data: bytes,
        is_canceled: Optional[Callable[[], bool]] = None,
    ) -> str:
        try:
            response = self.transport.request(
                "PUT", url, data=data, timeout=60,
                is_canceled=is_canceled or self.is_canceled,
            )
        except TransportCanceled as error:
            raise UploadCanceled("Upload canceled") from error
        except TransportError as error:
            raise GeoDelError("Part upload failed: Network, TLS or timeout failure") from error
        if not 200 <= response.status_code < 300:
            raise GeoDelError(f"Part upload failed: HTTP {response.status_code}")
        etag = response.header("ETag")
        if not etag:
            raise GeoDelError("Storage returned no ETag for uploaded part")
        return etag


def _version_tuple(version: str) -> Tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(version)
    major, minor, patch = (int(part) for part in parts)
    return major, minor, patch


def _upload_type(filename: str) -> Tuple[str, str]:
    lower = filename.lower()
    if lower.endswith(".zip"):
        return "shapefile", "application/zip"
    if lower.endswith(".geojson"):
        return "geojson", "application/geo+json"
    if lower.endswith(".json"):
        return "geojson", "application/json"
    raise GeoDelError("Supported upload formats are .zip, .geojson, and .json")


def _valid_folder(folder: Any) -> bool:
    return (
        isinstance(folder, dict)
        and isinstance(folder.get("id"), str)
        and isinstance(folder.get("name"), str)
    )


def _response_error(response: Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    reason = payload.get("error") or payload.get("message")
    return reason if isinstance(reason, str) else ""
