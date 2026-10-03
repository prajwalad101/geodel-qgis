from dataclasses import dataclass
from typing import Any, Optional

from .config import API_URL, WEB_URL


@dataclass(frozen=True)
class RecentUpload:
    filename: str
    status_label: str
    is_failed: bool
    failed_layers_tooltip: Optional[str]
    error_reason: Optional[str]
    health_warning_label: Optional[str]
    copy_share_url: Optional[str]
    details_url: Optional[str]
    details_label: Optional[str]


def project_recent_upload(upload: Any, server_url: str) -> RecentUpload:
    if not _valid_upload(upload):
        raise ValueError("invalid Upload")

    status = upload["status"]
    summary = upload["layerSummary"]
    web_url = _web_base_url(server_url)
    show_details = status in ("ready", "failed")

    return RecentUpload(
        filename=upload["originalFilename"],
        status_label=status.capitalize(),
        is_failed=status == "failed",
        failed_layers_tooltip=(
            "\n".join(
                f"{layer['name']}: {_short_reason(layer['reason'])}"
                for layer in summary["failedLayers"]
            )
            if status == "ready" and summary["failed"]
            else None
        ),
        error_reason=(
            _short_reason(upload["errorMessage"]) if status == "failed" else None
        ),
        health_warning_label=(
            _health_warning_label(summary["warningCount"])
            if status == "ready" and summary["warningCount"]
            else None
        ),
        copy_share_url=(
            share_url(server_url, upload["shareToken"])
            if status == "ready"
            else None
        ),
        details_url=f"{web_url}/{upload['id']}" if show_details else None,
        details_label="Open in web" if show_details else None,
    )


def share_url(server_url: str, token: str) -> str:
    return f"{_web_base_url(server_url)}/s/{token}"


def _web_base_url(server_url: str) -> str:
    base_url = server_url.rstrip("/")
    if base_url.endswith("/api/v1"):
        base_url = base_url[: -len("/api/v1")]
    return (
        WEB_URL
        if base_url == API_URL.removesuffix("/api/v1")
        else base_url
    )


def _short_reason(reason: Optional[str]) -> str:
    first_line = (reason or "Processing failed").splitlines()[0].strip()
    return first_line if len(first_line) <= 120 else f"{first_line[:117]}..."


def _health_warning_label(count: int) -> str:
    return f"⚠ {count} health warning{'s' if count != 1 else ''}"


def _valid_upload(upload: Any) -> bool:
    if not isinstance(upload, dict):
        return False
    summary = upload.get("layerSummary")
    return (
        isinstance(upload.get("id"), str)
        and isinstance(upload.get("originalFilename"), str)
        and upload.get("status") in ("pending", "processing", "ready", "failed")
        and isinstance(upload.get("shareToken"), str)
        and (
            upload.get("errorMessage") is None
            or isinstance(upload.get("errorMessage"), str)
        )
        and isinstance(summary, dict)
        and all(
            isinstance(summary.get(field), int) and summary[field] >= 0
            for field in ("total", "ready", "failed", "warningCount")
        )
        and isinstance(summary.get("failedLayers"), list)
        and all(
            isinstance(layer, dict)
            and isinstance(layer.get("name"), str)
            and isinstance(layer.get("reason"), str)
            for layer in summary["failedLayers"]
        )
        and summary["total"] == summary["ready"] + summary["failed"]
        and summary["failed"] == len(summary["failedLayers"])
        and (upload["status"] != "ready" or summary["ready"] > 0)
        and (upload["status"] != "failed" or summary["ready"] == 0)
    )
