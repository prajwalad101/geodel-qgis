"""QGIS-independent HTTP boundary for the domain client."""
from dataclasses import dataclass, field
import json
from typing import Any, Callable, Dict, Mapping, Optional, Protocol


class TransportError(Exception):
    """Network or TLS failure; messages must not contain credentials or URLs."""


class TransportTimeout(TransportError):
    """The request's deadline expired."""


class TransportCanceled(TransportError):
    """The caller canceled the request."""


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
    def request(
        self, method: str, url: str, *,
        headers: Optional[Mapping[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[bytes] = None,
        timeout: float = 15,
        is_canceled: Optional[Callable[[], bool]] = None,
    ) -> Response: ...
