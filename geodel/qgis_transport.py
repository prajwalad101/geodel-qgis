"""Blocking native QGIS HTTP, called only from plugin background tasks.

QGIS's blocking helper replaces cache attributes and rebuilds redirect requests.
A process-lifetime preprocessor, installed on module import on the GUI thread,
restores policy only inside this thread's request scope. It retains no keys
between calls and leaves every other QGIS request untouched. Registering and
removing QGIS's global preprocessor list from concurrent workers is unsafe.
"""
import json as json_codec
from threading import local
from time import monotonic
from typing import Any, Callable, Dict, Mapping, Optional

from qgis.PyQt.QtCore import QByteArray, QThread, QTimer, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import (
    QgsApplication, QgsBlockingNetworkRequest, QgsFeedback, QgsNetworkAccessManager,
)

from .transport import Response, TransportCanceled, TransportError, TransportTimeout


_request_scope = local()
_CREDENTIAL_HEADERS = ("Authorization", "X-Organization-Id", "X-Plugin-Version")


def _origin(url):
    return (url.scheme().lower(), url.host().lower(),
            url.port(443 if url.scheme().lower() == "https" else 80))


def _prepare_request(request):
    policy = getattr(_request_scope, "policy", None)
    if policy is None:
        return
    url = policy["url"].resolved(request.url())
    policy["hops"] += 1
    if (
        policy["hops"] > 6
        or url.scheme().lower() not in ("http", "https")
        or url.userName() or url.password()
        or (policy["url"].scheme().lower() == "https" and url.scheme().lower() != "https")
        or (policy["authenticated"] and _origin(url) != policy["origin"])
    ):
        policy["blocked"] = True
        # Refuse before sending any bytes; no unsafe redirect or credential log.
        request.setUrl(QUrl())
        for header in _CREDENTIAL_HEADERS:
            request.setRawHeader(header.encode(), QByteArray())
        return
    request.setUrl(url)
    policy["url"] = url
    for header in _CREDENTIAL_HEADERS:
        request.setRawHeader(header.encode(), QByteArray())
    for header, value in policy["headers"].items():
        request.setRawHeader(header.encode(), value.encode())
    request.setAttribute(QNetworkRequest.Attribute.CacheLoadControlAttribute,
                         QNetworkRequest.CacheLoadControl.AlwaysNetwork)
    request.setAttribute(QNetworkRequest.Attribute.CacheSaveControlAttribute, False)
    # API keys authenticate GeoDel; never reuse cached HTTP auth or cookies.
    request.setAttribute(QNetworkRequest.Attribute.AuthenticationReuseAttribute,
                         QNetworkRequest.LoadControl.Manual)
    request.setAttribute(QNetworkRequest.Attribute.CookieLoadControlAttribute,
                         QNetworkRequest.LoadControl.Manual)
    request.setAttribute(QNetworkRequest.Attribute.CookieSaveControlAttribute,
                         QNetworkRequest.LoadControl.Manual)


_policy_preprocessor = QgsNetworkAccessManager.setRequestPreprocessor(_prepare_request)


class QgisTransport:
    def request(
        self, method: str, url: str, *,
        headers: Optional[Mapping[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[bytes] = None,
        timeout: float = 15,
        is_canceled: Optional[Callable[[], bool]] = None,
    ) -> Response:
        if QThread.currentThread() == QgsApplication.instance().thread():
            raise TransportError("Network requests require a background task")
        if is_canceled and is_canceled():
            raise TransportCanceled("Request canceled")
        if method not in ("GET", "POST", "PUT", "DELETE"):
            raise TransportError("Unsupported HTTP method")
        from urllib.parse import urlencode
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params, doseq=True)
        request_url = QUrl(url)
        request_headers = dict(headers or {})
        if json is not None:
            data = json_codec.dumps(json).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        policy = {
            "url": request_url, "origin": _origin(request_url),
            "headers": request_headers, "hops": 0, "blocked": False,
            "authenticated": any(name in request_headers for name in _CREDENTIAL_HEADERS),
        }
        request = QNetworkRequest(request_url)
        feedback = QgsFeedback()
        blocking = QgsBlockingNetworkRequest()
        timer = QTimer()
        deadline = monotonic() + timeout
        expired = False
        canceled = False

        def check_request():
            nonlocal expired, canceled
            canceled = bool(is_canceled and is_canceled())
            expired = monotonic() >= deadline
            if canceled or expired:
                feedback.cancel()

        timer.setInterval(25)
        timer.timeout.connect(check_request)
        _request_scope.policy = policy
        timer.start()
        try:
            if method == "GET":
                code = blocking.get(request, True, feedback,
                    QgsBlockingNetworkRequest.RequestFlag.EmptyResponseIsValid)
            elif method == "POST":
                code = blocking.post(request, QByteArray(data or b""), True, feedback)
            elif method == "PUT":
                code = blocking.put(request, QByteArray(data or b""), feedback)
            else:
                code = blocking.deleteResource(request, feedback)
            if canceled or (is_canceled and is_canceled()):
                raise TransportCanceled("Request canceled")
            if expired or monotonic() >= deadline or code == QgsBlockingNetworkRequest.ErrorCode.TimeoutError:
                raise TransportTimeout("Request timed out")
            if policy["blocked"]:
                raise TransportError("Unsafe or excessive redirect")
            reply = blocking.reply()
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            # QGIS reports HTTP 4xx/5xx as errors too; preserve status for the client.
            if not status or (code != QgsBlockingNetworkRequest.ErrorCode.NoError and int(status) < 400):
                raise TransportError("Network or TLS failure")
            response_headers = {
                bytes(name).decode("latin-1"): bytes(reply.rawHeader(name)).decode("latin-1")
                for name in reply.rawHeaderList()
            }
            return Response(int(status), bytes(reply.content()), response_headers)
        finally:
            timer.stop()
            timer.timeout.disconnect(check_request)
            # QGIS connects feedback to its helper internally. Release all slots.
            feedback.canceled.disconnect()
            del _request_scope.policy
