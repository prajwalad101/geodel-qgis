"""QGIS-independent HTTP boundary for the domain client."""
from dataclasses import dataclass, field
from contextlib import nullcontext
import json
import os
from pathlib import Path
from os import stat_result
from typing import Any, Callable, ContextManager, Dict, Mapping, Optional, Protocol, Union


class TransportError(Exception):
    """Network or TLS failure; messages must not contain credentials or URLs."""


class TransportTimeout(TransportError):
    """The request's deadline expired."""


class TransportConnectionError(TransportError):
    """Transient connection failure; safe to retry idempotent requests."""


class TransportCanceled(TransportError):
    """The caller canceled the request."""


def validate_upload_file(path, expected, descriptor=None):
    def identity(stat):
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    if (identity(path.stat()) != identity(expected)
            or (descriptor is not None and identity(os.fstat(descriptor)) != identity(expected))):
        raise OSError("Upload file changed during transfer")


@dataclass(frozen=True)
class Response:
    status_code: int
    body: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        return json.loads(self.body)

    def header(self, name: str) -> Optional[str]:
        return next((value for key, value in self.headers.items()
                     if key.lower() == name.lower()), None)


class Transport(Protocol):
    def session(self) -> ContextManager[None]:
        return nullcontext()

    def request(
        self, method: str, url: str, *,
        headers: Optional[Mapping[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Union[bytes, Path]] = None,
        file_stat: Optional[stat_result] = None,
        timeout: float = 15,
        is_canceled: Optional[Callable[[], bool]] = None,
        upload_progress: Optional[Callable[[int], None]] = None,
    ) -> Response: ...
