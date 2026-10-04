"""Blocking native QGIS HTTP, called only from plugin background tasks.

Each call owns a fresh QGIS network manager and follows redirects explicitly.
Reload-safe process-lifetime hooks, installed on the GUI thread,
restore policy only inside this thread's request scope. They retain no keys
between calls and leave every other QGIS request untouched. Registering and
removing QGIS's global preprocessor list from concurrent workers is unsafe.
"""
from dataclasses import dataclass
import json as json_codec
from threading import local
from time import monotonic
from typing import Any, Callable, Dict, Mapping, Optional, Tuple
from urllib.parse import urlencode

from qgis.PyQt.QtCore import (
    QByteArray, QCoreApplication, QEvent, QEventLoop, QObject, Qt, QThread, QTimer, QUrl, pyqtSignal,
)
from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest, QSslError
from qgis.core import QgsApplication, QgsNetworkAccessManager

from .transport import Response, TransportCanceled, TransportError, TransportTimeout


_CREDENTIAL_HEADERS = ("Authorization", "X-Organization-Id", "X-Plugin-Version")


def _origin(url):
    return (url.scheme().lower(), url.host().lower(),
            url.port(443 if url.scheme().lower() == "https" else 80))


@dataclass
class _RequestPolicy:
    url: QUrl
    origin: Tuple[str, str, int]
    headers: Dict[str, str]
    authenticated: bool
    hops: int = 0
    blocked: bool = False


def _prepare_request(request):
    policy = getattr(_request_scope, "policy", None)
    if policy is None:
        return
    url = policy.url.resolved(request.url())
    policy.hops += 1
    if (
        policy.hops > 6
        or url.scheme().lower() not in ("http", "https")
        or url.userName() or url.password()
        or (policy.url.scheme().lower() == "https" and url.scheme().lower() != "https")
        or (policy.authenticated and _origin(url) != policy.origin)
    ):
        policy.blocked = True
        # Refuse before sending any bytes; no unsafe redirect or credential log.
        request.setUrl(QUrl())
        for header in _CREDENTIAL_HEADERS:
            request.setRawHeader(header.encode(), QByteArray())
        return
    request.setUrl(url)
    policy.url = url
    for header in _CREDENTIAL_HEADERS:
        request.setRawHeader(header.encode(), QByteArray())
    for header, value in policy.headers.items():
        request.setRawHeader(header.encode(), value.encode())
    request.setAttribute(QNetworkRequest.Attribute.CacheLoadControlAttribute,
                         QNetworkRequest.CacheLoadControl.AlwaysNetwork)
    request.setAttribute(QNetworkRequest.Attribute.CacheSaveControlAttribute, False)
    # The isolated manager has no origin credentials. Allow configured proxy
    # authentication; Qt's Manual flag would also disable proxy retries.
    request.setAttribute(QNetworkRequest.Attribute.AuthenticationReuseAttribute,
                         QNetworkRequest.LoadControl.Automatic)
    request.setAttribute(QNetworkRequest.Attribute.CookieLoadControlAttribute,
                         QNetworkRequest.LoadControl.Manual)
    request.setAttribute(QNetworkRequest.Attribute.CookieSaveControlAttribute,
                         QNetworkRequest.LoadControl.Manual)
    request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                         QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)


def _prepare_reply(_request, reply):
    if getattr(_request_scope, "policy", None) is not None:
        # Keep Qt's certificate verification, but don't invoke QGIS's modal SSL
        # handler: it locks this worker on a GUI semaphore and defeats deadlines.
        # QGIS has already applied the profile's CA and TLS configuration.
        reply.sslErrors.disconnect()
        host_port = f"{reply.url().host()}:{reply.url().port(443)}"
        config = QgsApplication.authManager().sslCertCustomConfigByHost(host_port)
        if not config.isNull():
            # These QSslErrors include the saved certificate: Qt only accepts
            # matching per-host, per-certificate exceptions chosen by the user.
            # All other certificate errors still fail without a dialog.
            allowed_errors = [
                QSslError(error, config.sslCertificate())
                for error in config.sslIgnoredErrorEnums()
            ]
            if allowed_errors:
                reply.ignoreSslErrors(allowed_errors)


# QGIS deletes plugin modules on unload, but retains its preprocessors. Store
# shared scope and dispatchers on the stable main-thread NAM wrapper so reload
# updates behavior without accumulating callbacks or dropping active cleanup.
class _PolicyHooks:
    def __init__(self):
        self.scope = local()
        self.prepare_request = _prepare_request
        self.prepare_reply = _prepare_reply
        self.request_identifier = ""
        self.reply_identifier = ""


_policy_owner = QgsNetworkAccessManager.instance()
_hooks = getattr(_policy_owner, "_geodel_network_hooks", None)
if _hooks is None:
    _hooks = _PolicyHooks()
    _policy_owner._geodel_network_hooks = _hooks
_request_scope = _hooks.scope
_hooks.prepare_request = _prepare_request
_hooks.prepare_reply = _prepare_reply
if not _hooks.request_identifier:
    _hooks.request_identifier = QgsNetworkAccessManager.setRequestPreprocessor(
        lambda request, hooks=_hooks: hooks.prepare_request(request))
if not _hooks.reply_identifier:
    _hooks.reply_identifier = QgsNetworkAccessManager.setReplyPreprocessor(
        lambda request, reply, hooks=_hooks: hooks.prepare_reply(request, reply))


class _RequestCancellation(QObject):
    requested = pyqtSignal()


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
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params, doseq=True)
        request_url = QUrl(url)
        request_headers = dict(headers or {})
        if json is not None:
            data = json_codec.dumps(json).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        policy = _RequestPolicy(
            request_url, _origin(request_url), request_headers,
            any(name.lower() in {header.lower() for header in _CREDENTIAL_HEADERS}
                for name in request_headers),
        )
        # Construction retains QGIS's proxy factory (which resolves through the
        # current thread's configured manager) and TLS request preparation, but
        # gives this call its own authentication/connection cache. Do not call
        # setupDefaultProxyAndCache: that wires up shared cookies and auth dialogs.
        manager = QgsNetworkAccessManager()
        timer = QTimer()
        cancellation = _RequestCancellation(manager)
        abort_connection = None
        loop = None
        result = None
        reply_pending = False
        deadline = monotonic() + timeout
        expired = False
        canceled = False

        def check_request():
            nonlocal expired, canceled
            canceled = bool(is_canceled and is_canceled())
            expired = monotonic() >= deadline
            if (canceled or expired) and reply_pending:
                cancellation.requested.emit()

        def manager_timeout(_reply):
            nonlocal expired
            expired = True

        def finished(completed_reply):
            nonlocal reply_pending, result
            reply_pending = False
            # Snapshot the live reply supplied by Qt, before returning to the
            # event loop. Never read or abort the returned wrapper afterward.
            status = completed_reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            response_headers = {
                bytes(name).decode("latin-1"): bytes(completed_reply.rawHeader(name)).decode("latin-1")
                for name in completed_reply.rawHeaderList()
            }
            result = (
                Response(
                    int(status or 0),
                    bytes(completed_reply.readAll()) if completed_reply.isReadable() else b"",
                    response_headers,
                ),
                completed_reply.error(),
                completed_reply.attribute(QNetworkRequest.Attribute.RedirectionTargetAttribute),
            )
            if abort_connection is not None:
                QObject.disconnect(abort_connection)
            loop.quit()

        # These callbacks access worker-owned Qt objects. Do not queue them
        # past completion or destruction of the request's manager and reply.
        manager.requestTimedOut[QNetworkReply].connect(manager_timeout, Qt.ConnectionType.DirectConnection)
        # QgsNetworkAccessManager also declares finished(QgsNetworkReplyContent).
        # Bind the base Qt signal explicitly to receive its live QNetworkReply.
        manager_finished = QNetworkAccessManager.finished.__get__(manager, QNetworkAccessManager)
        manager_finished.connect(finished, Qt.ConnectionType.DirectConnection)
        timer.setInterval(25)
        timer.timeout.connect(check_request, Qt.ConnectionType.DirectConnection)
        _request_scope.policy = policy
        timer.start()
        try:
            next_url = request_url
            while True:
                check_request()
                if canceled:
                    raise TransportCanceled("Request canceled")
                if expired:
                    raise TransportTimeout("Request timed out")
                loop = QEventLoop()
                result = None
                abort_connection = None
                reply_pending = True
                request = QNetworkRequest(next_url)
                if method == "GET":
                    reply = manager.get(request)
                elif method == "POST":
                    reply = manager.post(request, QByteArray(data or b""))
                elif method == "PUT":
                    reply = manager.put(request, QByteArray(data or b""))
                else:
                    reply = manager.deleteResource(request)
                if result is None:
                    # A native Qt connection stops targeting a deleted reply
                    # automatically; a Python callback calling abort() does not.
                    abort_connection = cancellation.requested.connect(reply.abort, Qt.ConnectionType.DirectConnection)
                    loop.exec()
                if canceled or (is_canceled and is_canceled()):
                    raise TransportCanceled("Request canceled")
                if expired or monotonic() >= deadline:
                    raise TransportTimeout("Request timed out")
                if policy.blocked:
                    raise TransportError("Unsafe or excessive redirect")
                if result is None:
                    raise TransportError("Network request ended without a response")
                response, error, redirect = result
                if error == QNetworkReply.NetworkError.TimeoutError:
                    raise TransportTimeout("Request timed out")
                # Qt reports HTTP 4xx/5xx as errors too; preserve status for the client.
                if not response.status_code or (
                    error != QNetworkReply.NetworkError.NoError and response.status_code < 400
                ):
                    raise TransportError("Network or TLS failure")
                if redirect is not None and 300 <= response.status_code < 400:
                    next_url = policy.url.resolved(redirect)
                    continue
                return response
        finally:
            timer.stop()
            timer.timeout.disconnect(check_request)
            del _request_scope.policy
            if reply_pending:
                cancellation.requested.emit()
            # Destroy in the worker thread, including replies and cached credentials.
            manager.deleteLater()
            QCoreApplication.sendPostedEvents(manager, QEvent.Type.DeferredDelete)
