"""Pure-Python client for the QGIS plugin API."""

from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from secrets import randbelow
from threading import Event, Lock
from time import monotonic, sleep
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from .transport import (
    Response, Transport, TransportCanceled, TransportConnectionError, TransportError, TransportTimeout,
    validate_upload_file,
)

from .config import DEFAULT_CONFIG, PRODUCT_NAME, PluginConfig
from .recent_upload import RecentUpload, project_recent_upload


class GeoDelError(Exception):
    """API request failed."""


class AuthenticationError(GeoDelError):
    """The API could not authenticate the request."""


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
        config: Optional[PluginConfig] = None,
    ) -> None:
        base_url = base_url.rstrip("/")
        self.base_url = (
            base_url if base_url.endswith("/api/v1") else f"{base_url}/api/v1"
        )
        self.api_key = api_key
        self.plugin_version = plugin_version
        self.transport = transport
        self.is_canceled = is_canceled
        self.config = config if config is not None else DEFAULT_CONFIG

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

    def requires_update(self, metadata: Optional[Dict[str, Any]] = None) -> bool:
        minimum = (metadata if metadata is not None else self.get_meta())["minPluginVersion"]
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
        if file_size > self.config.max_file_size_bytes:
            raise GeoDelError(f"Upload file exceeds the {self.config.file_size_label} limit")

        try:
            self.config.validate_filename(filename)
        except ValueError as error:
            raise GeoDelError(str(error)) from error
        upload_format, content_type = _upload_type(filename)
        if is_canceled and is_canceled():
            raise UploadCanceled("Upload canceled")

        metadata = {
            "fileSizeKb": (file_size + 1023) // 1024,
            "lastModified": int(file_stat.st_mtime * 1000),
            "format": upload_format,
        }
        progress_lock = Lock()
        sent: Dict[int, int] = {}

        def report(part_number, size, uploaded):
            if progress:
                with progress_lock:
                    sent[part_number] = max(sent.get(part_number, 0), min(size, max(0, uploaded)))
                    progress(min(99, sum(sent.values()) / file_size * 100))

        with self.transport.session():
            if file_size <= self.config.single_put_threshold_bytes:
                signed = self._get(
                    "/uploads/s3/params", organization_id,
                    params={"filename": filename, "type": content_type,
                            **{f"metadata[{name}]": value for name, value in metadata.items()}},
                    is_canceled=is_canceled,
                )
                attempt_id = signed.get("attemptId")
                if not isinstance(attempt_id, str) or not attempt_id or signed.get("method") != "PUT":
                    raise GeoDelError(f"{PRODUCT_NAME} returned invalid upload parameters")
                url = _signed_url(signed)
                headers = signed.get("headers")
                if headers != {"Content-Type": content_type}:
                    raise GeoDelError(f"{PRODUCT_NAME} returned invalid upload headers")
                # ponytail: single-PUT attempts expire; immediate cleanup needs an API abort endpoint.
                self._put_part(url, path, is_canceled, headers=headers, file_stat=file_stat,
                               upload_progress=lambda uploaded: report(1, file_size, uploaded), require_etag=False)
                report(1, file_size, file_size)
                registered_id = self._register(attempt_id, organization_id, folder_id, is_canceled)
            else:
                initialized = self._request(
                    "POST", "/uploads/s3/multipart", organization_id, is_canceled=is_canceled,
                    json={"filename": filename, "type": content_type, "metadata": metadata},
                )
                attempt_id, key = initialized.get("uploadId"), initialized.get("key")
                if not isinstance(attempt_id, str) or not attempt_id or not isinstance(key, str) or not key:
                    raise GeoDelError(f"{PRODUCT_NAME} returned an invalid multipart response")
                try:
                    parts = self._upload_parts(path, file_stat, attempt_id, key, organization_id, report, is_canceled)
                    validate_upload_file(path, file_stat)
                    self._request(
                        "POST", f"/uploads/s3/multipart/{attempt_id}/complete", organization_id,
                        params={"key": key}, json={"parts": parts}, is_canceled=is_canceled,
                    )
                    registered_id = self._register(attempt_id, organization_id, folder_id, is_canceled)
                except (GeoDelError, OSError) as error:
                    try:
                        self._request(
                            "DELETE", f"/uploads/s3/multipart/{attempt_id}", organization_id,
                            params={"key": key}, is_canceled=lambda: False,
                        )
                    except GeoDelError:
                        pass
                    if isinstance(error, GeoDelError):
                        raise
                    raise GeoDelError(f"Could not read upload file: {error}") from error
        if progress:
            progress(100)
        return registered_id

    def _register(self, attempt_id, organization_id, folder_id, is_canceled):
        if is_canceled and is_canceled():
            raise UploadCanceled("Upload canceled")
        registered = self._request(
            "POST", "/uploads/register", organization_id, is_canceled=lambda: False,
            json={"attemptId": attempt_id, **({"folderId": folder_id} if folder_id else {})},
        )
        registered_id = registered.get("id")
        if not isinstance(registered_id, str) or not registered_id:
            raise GeoDelError(f"{PRODUCT_NAME} returned an invalid upload response")
        return registered_id

    def _upload_parts(self, path, file_stat, attempt_id, key, organization_id, report, is_canceled):
        file_size = file_stat.st_size
        pending: Queue[int] = Queue()
        for number in range(1, (file_size + self.config.part_size_bytes - 1) // self.config.part_size_bytes + 1):
            pending.put(number)
        stopped = Event()
        parts = []
        failures = []
        result_lock = Lock()

        def canceled():
            return stopped.is_set() or bool(is_canceled and is_canceled())

        def worker():
            try:
                with self.transport.session(), path.open("rb") as source:
                    validate_upload_file(path, file_stat, source.fileno())
                    while not canceled():
                        try:
                            number = pending.get_nowait()
                        except Empty:
                            return
                        size = min(self.config.part_size_bytes, file_size - (number - 1) * self.config.part_size_bytes)
                        source.seek((number - 1) * self.config.part_size_bytes)
                        validate_upload_file(path, file_stat, source.fileno())
                        chunk = source.read(size)
                        validate_upload_file(path, file_stat, source.fileno())
                        if len(chunk) != size:
                            raise GeoDelError("Upload file changed during transfer")
                        signed = self._request(
                            "GET", f"/uploads/s3/multipart/{attempt_id}/{number}", organization_id,
                            params={"key": key}, is_canceled=canceled, retry=True,
                        )
                        etag = self._put_part(
                            _signed_url(signed), chunk, canceled,
                            upload_progress=lambda uploaded: report(number, size, uploaded),
                        )
                        validate_upload_file(path, file_stat, source.fileno())
                        report(number, size, size)
                        with result_lock:
                            parts.append({"PartNumber": number, "ETag": etag})
                        del chunk
            except (GeoDelError, OSError) as error:
                with result_lock:
                    if not stopped.is_set():
                        failures.append(error)
                        stopped.set()

        with ThreadPoolExecutor(max_workers=self.config.part_concurrency) as pool:
            futures = [pool.submit(worker) for _ in range(min(self.config.part_concurrency, pending.qsize()))]
            for future in futures:
                future.result()
        if failures:
            raise failures[0]
        if canceled():
            raise UploadCanceled("Upload canceled")
        return sorted(parts, key=lambda part: part["PartNumber"])

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
        while monotonic() - started < self.config.processing_timeout_seconds:
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
                progress(min(99, 90 + elapsed / self.config.processing_timeout_seconds * 9))
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
            response = self._send(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                timeout=self.config.request_timeout_seconds,
                is_canceled=kwargs.pop("is_canceled", None) or self.is_canceled,
                retry=kwargs.pop("retry", False),
                **{key: value for key, value in kwargs.items() if value is not None},
            )
        except TransportCanceled as error:
            raise UploadCanceled("Upload canceled") from error
        except TransportError as error:
            raise ServerUnavailableError(
                f"{PRODUCT_NAME} request failed: Network, TLS or timeout failure"
            ) from error
        if response.status_code == 401:
            raise AuthenticationError("Authentication failed. Reconnect and try again.")
        if response.status_code == 403:
            raise AuthorizationError(_http_error_message(response))
        if response.status_code >= 400 or response.status_code < 200:
            failure = ServerUnavailableError if response.status_code >= 500 else GeoDelError
            raise failure(_http_error_message(response))
        try:
            payload = response.json()
        except (ValueError, UnicodeError) as error:
            raise GeoDelError(f"{PRODUCT_NAME} returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise GeoDelError(f"{PRODUCT_NAME} returned an invalid response")
        return payload

    def _send(self, method, url, *, is_canceled=None, retry=False, **options):
        for attempt in range(len(self.config.retry_delays_seconds) + 1):
            if is_canceled and is_canceled():
                raise TransportCanceled("Request canceled")
            response = None
            try:
                response = self.transport.request(method, url, is_canceled=is_canceled, **options)
            except (TransportConnectionError, TransportTimeout):
                if not retry or attempt == len(self.config.retry_delays_seconds):
                    raise
            else:
                if not retry or not (response.status_code in (408, 429) or response.status_code >= 500):
                    return response
                if attempt == len(self.config.retry_delays_seconds):
                    return response
            delay = self.config.retry_delays_seconds[attempt] + randbelow(251) / 1000
            if response:
                delay = max(delay, _retry_after(response))
            while delay > 0:
                if is_canceled and is_canceled():
                    raise TransportCanceled("Request canceled")
                interval = min(0.05, delay)
                sleep(interval)
                delay -= interval
        raise AssertionError("Retry budget exhausted without a result")

    def _put_part(
        self, url: str, data: Union[bytes, Path],
        is_canceled: Optional[Callable[[], bool]] = None, *,
        headers: Optional[Dict[str, str]] = None,
        upload_progress: Optional[Callable[[int], None]] = None,
        require_etag: bool = True,
        file_stat=None,
    ) -> str:
        try:
            response = self._send(
                "PUT", url, data=data, timeout=self.config.upload_part_timeout_seconds,
                is_canceled=is_canceled or self.is_canceled, retry=True,
                **({"headers": headers} if headers else {}),
                **({"upload_progress": upload_progress} if upload_progress else {}),
                **({"file_stat": file_stat} if file_stat is not None else {}),
            )
        except TransportCanceled as error:
            raise UploadCanceled("Upload canceled") from error
        except TransportError as error:
            raise GeoDelError("Part upload failed: Network, TLS or timeout failure") from error
        except OSError as error:
            raise GeoDelError(f"Could not read upload file: {error}") from error
        if not 200 <= response.status_code < 300:
            raise GeoDelError(f"Part upload failed: HTTP {response.status_code}")
        etag = response.header("ETag")
        if require_etag and not etag:
            raise GeoDelError("Storage returned no ETag for uploaded part")
        return etag or ""


def _signed_url(payload):
    url = payload.get("url")
    if not isinstance(url, str) or not url:
        raise GeoDelError(f"{PRODUCT_NAME} returned an invalid part upload URL")
    return url


def _retry_after(response):
    value = response.header("Retry-After")
    if not value:
        return 0
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return 0
    return max(0, min(30, seconds))


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


def _http_error_message(response: Response) -> str:
    # Only interpret documented reason codes or exact server messages with
    # their expected status. Never display arbitrary error bodies or infer an
    # API-key problem from a generic denial.
    try:
        payload = response.json()
    except ValueError:
        payload = None
    status = response.status_code
    reason = payload.get("reason") if isinstance(payload, dict) else None
    messages = {
        "trial_expired": (
            f"Your workspace trial has expired. Manage your subscription in {PRODUCT_NAME}."
        ),
        "capacity_exhausted": (
            "This upload would exceed your workspace storage capacity. "
            f"Delete files or upgrade your plan in {PRODUCT_NAME}."
        ),
        "subscription_on_hold": (
            "Your workspace subscription is on hold. "
            f"Update your payment method in {PRODUCT_NAME}."
        ),
        "subscription_required": (
            "Your workspace needs a subscription to upload files. "
            f"Manage your subscription in {PRODUCT_NAME}."
        ),
    }
    if status == 403 and isinstance(reason, str) and reason in messages:
        return messages[reason]
    message = (payload.get("error") or payload.get("message")) if isinstance(payload, dict) else None
    known_messages = {
        (400, "Invalid request"): (
            f"{PRODUCT_NAME} rejected the request as invalid. Try again; if it persists, contact support."
        ),
        (400, "X-Organization-Id header is required for API key requests"): (
            "No workspace was sent with this request. Select a workspace and reconnect."
        ),
        (400, "uploaded object size is unavailable"): (
            f"{PRODUCT_NAME} could not verify the uploaded file size. Try uploading again."
        ),
        (400, "uploaded object size does not match request"): (
            "The uploaded file size does not match the submitted size. Try uploading again."
        ),
        (400, "Multipart upload reference is invalid"): (
            "The upload reference is invalid. Start the upload again."
        ),
        (403, "Upload attempt does not belong to the current session"): (
            "This upload attempt belongs to a different account or workspace. "
            "Reconnect to the intended workspace and start again."
        ),
        (404, "Upload attempt not found"): (
            "The upload attempt was not found. Start the upload again."
        ),
        (404, "Upload not found"): "The upload was not found. Refresh recent uploads.",
        (404, "Folder not found"): "The selected folder was not found. Refresh and choose a folder again.",
        (404, "Organization not found"): "The selected workspace was not found. Refresh and select a workspace again.",
    }
    if isinstance(message, str) and (status, message) in known_messages:
        return known_messages[status, message]
    if status == 403:
        return f"Request denied by {PRODUCT_NAME} (HTTP 403)."
    if status == 413:
        return "The upload request exceeds the server's size limit. Use a smaller file."
    if status == 429:
        return f"Too many requests to {PRODUCT_NAME}. Wait a moment and try again."
    if status >= 500:
        return f"{PRODUCT_NAME} server error (HTTP {status}). Try again later."
    return f"{PRODUCT_NAME} request failed (HTTP {status})."
