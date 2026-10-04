"""Native transport tests against local fixtures; no external network required."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
import time
from threading import Thread
import unittest

from qgis.PyQt.QtWidgets import QApplication
from qgis.core import QgsApplication, QgsTask


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.server.received.append((self.command, self.path, {name.lower(): value for name, value in self.headers.items()},
                                     self.rfile.read(int(self.headers.get("Content-Length", 0)))))
        if getattr(self.server, "proxy_auth", False) and not self.headers.get("Proxy-Authorization"):
            self.send_response(407)
            self.send_header("Proxy-Authenticate", 'Basic realm="local-proxy"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if getattr(self.server, "auth_challenge", False) and not self.headers.get("Authorization"):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="local-origin"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/redirect"):
            self.send_response(307)
            self.send_header("Location", self.server.redirect_url)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/slow"):
            self.server.started.set()
            time.sleep(0.4)
        status, body = (self.server.route(self.command, self.path)
                        if hasattr(self.server, "route") else (self.server.status, self.server.body))
        self.send_response(status)
        self.send_header("Content-Length", "999" if self.path.startswith("/truncated") else str(len(body)))
        self.send_header("ETag", '\"local-etag\"')
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        try:
            self.wfile.write(body)
            if self.path.startswith("/truncated"):
                self.close_connection = True
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_POST = do_GET
    do_PUT = do_GET
    do_DELETE = do_GET



class NetworkRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        from threading import Event
        self.server.received = []
        self.server.status = 200
        self.server.body = b'{"organizations": [{"id":"org-1", "name":"Local"}]}'
        self.server.started = Event()
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def in_task(self, operation):
        import time
        outcome = []
        task = QgsTask.fromFunction("Local transport fixture", lambda task: operation(task),
                                    on_finished=lambda error, value=None: outcome.append((error, value)))
        QgsApplication.taskManager().addTask(task)
        deadline = time.monotonic() + 5
        while not outcome and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)
        self.assertTrue(outcome, "Native request failed to finish")
        error, value = outcome[0]
        if error:
            raise error
        return value

    def test_workspaces_use_native_transport_in_background_task(self):
        from geodel.client import GeoDelClient
        from geodel.qgis_transport import QgisTransport

        result = self.in_task(lambda _task: GeoDelClient(
            self.url, "synthetic-key", "0.1.0", QgisTransport(),
        ).list_organizations())
        self.assertEqual(result, [{"id": "org-1", "name": "Local"}])
        method, path, headers, _body = self.server.received[0]
        self.assertEqual((method, path), ("GET", "/api/v1/organizations"))
        self.assertEqual(headers["authorization"], "Bearer synthetic-key")

    def test_same_origin_redirect_restores_auth_and_tenancy(self):
        from geodel.qgis_transport import QgisTransport
        self.server.redirect_url = "/destination"
        headers = {"Authorization": "Bearer synthetic-key", "X-Organization-Id": "org-1",
                   "X-Plugin-Version": "0.1.0"}
        self.in_task(lambda _task: QgisTransport().request("GET", self.url + "/redirect", headers=headers))
        self.assertEqual(self.server.received[-1][1], "/destination")
        for name, value in headers.items():
            self.assertEqual(self.server.received[-1][2][name.lower()], value)

    def test_cross_origin_api_redirect_is_refused_before_sending_credentials(self):
        from geodel.qgis_transport import QgisTransport
        from geodel.transport import TransportError
        self.server.redirect_url = self.url.replace("127.0.0.1", "localhost") + "/destination"
        with self.assertRaisesRegex(TransportError, "redirect"):
            self.in_task(lambda _task: QgisTransport().request("GET", self.url + "/redirect", headers={
                "Authorization": "Bearer synthetic-key", "X-Organization-Id": "org-1"}))
        self.assertEqual(len(self.server.received), 1)

    def test_signed_storage_redirect_sends_bytes_without_geodel_headers(self):
        from geodel.qgis_transport import QgisTransport
        self.server.redirect_url = self.url.replace("127.0.0.1", "localhost") + "/destination"
        response = self.in_task(lambda _task: QgisTransport().request(
            "PUT", self.url + "/redirect?signature=synthetic", data=b"original bytes"))
        self.assertEqual(response.header("etag"), '\"local-etag\"')
        self.assertEqual([row[3] for row in self.server.received], [b"original bytes", b"original bytes"])
        for _method, _path, headers, _body in self.server.received:
            for name in ("Authorization", "X-Organization-Id", "X-Plugin-Version"):
                self.assertNotIn(name.lower(), headers)

    def test_authenticated_responses_bypass_cache_and_remain_tenant_specific(self):
        from geodel.qgis_transport import QgisTransport
        from qgis.core import QgsNetworkAccessManager
        from qgis.PyQt.QtNetwork import QNetworkRequest
        requests = []
        def record(request):
            requests.append(QNetworkRequest(request))
        # Added after plugin policy so actual outgoing cache attributes are observed.
        identifier = QgsNetworkAccessManager.setRequestPreprocessor(record)
        try:
            for key, organization in (("key-one", "org-one"), ("key-two", "org-two")):
                self.in_task(lambda _task: QgisTransport().request("GET", self.url, headers={
                    "Authorization": "Bearer " + key, "X-Organization-Id": organization}))
        finally:
            QgsNetworkAccessManager.removeRequestPreprocessor(identifier)
        self.assertEqual(len(self.server.received), 2)
        self.assertEqual(self.server.received[1][2]["x-organization-id"], "org-two")
        for request in requests:
            self.assertEqual(request.attribute(QNetworkRequest.Attribute.CacheLoadControlAttribute),
                             QNetworkRequest.CacheLoadControl.AlwaysNetwork)
            self.assertFalse(request.attribute(QNetworkRequest.Attribute.CacheSaveControlAttribute))

    def test_request_deadline_aborts_slow_request_and_next_request_succeeds(self):
        from geodel.qgis_transport import QgisTransport
        from geodel.transport import TransportTimeout
        def operation(_task):
            started = time.monotonic()
            with self.assertRaises(TransportTimeout):
                QgisTransport().request("GET", self.url + "/slow", timeout=0.1)
            self.assertLess(time.monotonic() - started, 0.35)
            return QgisTransport().request("GET", self.url)
        self.assertEqual(self.in_task(operation).status_code, 200)

    def test_finished_reply_disposal_preserves_response_errors_and_cleanup(self):
        from unittest.mock import patch
        from qgis.PyQt.QtCore import QCoreApplication, QEvent, QEventLoop, Qt
        from qgis.core import QgsNetworkAccessManager
        import geodel.qgis_transport as transport
        from geodel.transport import TransportCanceled, TransportTimeout

        disposed = []
        test = self

        class DrainDeferredDeletesLoop(QEventLoop):
            def exec(self):
                before = len(disposed)
                result = super().exec()
                # Pin the CI timing: Qt disposes a finished reply before the
                # transport resumes after its nested event loop.
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                test.assertGreater(len(disposed), before, "Finished reply was not disposed")
                return result

        class DisposeRepliesManager(QgsNetworkAccessManager):
            def get(self, request):
                reply = super().get(request)
                reply.destroyed.connect(lambda: disposed.append(True), Qt.ConnectionType.DirectConnection)
                reply.finished.connect(reply.deleteLater, Qt.ConnectionType.DirectConnection)
                if request.url().path() == "/completed":
                    completed_loop = QEventLoop()
                    reply.finished.connect(completed_loop.quit, Qt.ConnectionType.DirectConnection)
                    if not reply.isFinished():
                        completed_loop.exec()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                return reply

        with patch.object(transport, "QgsNetworkAccessManager", DisposeRepliesManager), \
                patch.object(transport, "QEventLoop", DrainDeferredDeletesLoop):
            def operation(_task):
                response = transport.QgisTransport().request("GET", self.url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.body, self.server.body)
                self.assertEqual(response.header("etag"), '\"local-etag\"')
                completed = transport.QgisTransport().request("GET", self.url + "/completed")
                self.assertEqual(completed.body, self.server.body)
                self.server.redirect_url = "/destination"
                redirected = transport.QgisTransport().request("GET", self.url + "/redirect")
                self.assertEqual(redirected.body, self.server.body)
                with self.assertRaises(TransportTimeout):
                    transport.QgisTransport().request("GET", self.url + "/slow", timeout=0.1)
                cancel_at = time.monotonic() + 0.05
                with self.assertRaises(TransportCanceled):
                    transport.QgisTransport().request(
                        "GET", self.url + "/slow", is_canceled=lambda: time.monotonic() >= cancel_at)
                self.assertEqual(transport.QgisTransport().request("GET", self.url).status_code, 200)
                self.server.status = 503
                self.assertEqual(transport.QgisTransport().request("GET", self.url).status_code, 503)
            self.in_task(operation)

    def test_cancel_active_task_aborts_reply_and_stops_timer(self):
        from geodel.qgis_transport import QgisTransport
        from geodel.transport import TransportCanceled
        from qgis.PyQt.QtCore import QTimer
        tasks = []
        def operation(task):
            tasks.append(task)
            with self.assertRaises(TransportCanceled):
                QgisTransport().request("GET", self.url + "/slow", is_canceled=task.isCanceled)
            # Ignore original cancellation for a bounded cleanup request.
            return QgisTransport().request("DELETE", self.url + "/cleanup", timeout=0.2)
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: tasks[0].cancel() if tasks and self.server.started.is_set() else None)
        timer.start()
        try:
            self.assertEqual(self.in_task(operation).status_code, 200)
        finally:
            timer.stop()
            timer.timeout.disconnect()
        self.assertEqual(self.server.received[-1][0], "DELETE")

    def test_truncated_success_response_is_network_failure(self):
        from geodel.qgis_transport import QgisTransport
        from geodel.transport import TransportError
        with self.assertRaises(TransportError):
            self.in_task(lambda _task: QgisTransport().request("PUT", self.url + "/truncated", data=b"bytes"))

    def test_tls_verification_rejects_self_signed_certificate(self):
        import os
        from pathlib import Path
        import ssl
        import subprocess
        from geodel.qgis_transport import QgisTransport
        from geodel.transport import TransportError

        root = Path(os.environ["GEODEL_RUNTIME_ROOT"])
        certificate, key = root / "fixture.crt", root / "fixture.key"
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(certificate), "-days", "1",
            "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, key)
        secure = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        secure.received = []
        secure.status = 200
        secure.body = b'{}'
        secure.socket = context.wrap_socket(secure.socket, server_side=True)
        Thread(target=secure.serve_forever, daemon=True).start()
        try:
            from qgis.core import QgsNetworkAccessManager
            from qgis.PyQt.QtCore import Qt
            prompts = []
            def operation(_task):
                manager = QgsNetworkAccessManager.instance()
                def pending_dialog(*_args):
                    prompts.append(True)
                    time.sleep(0.5)
                manager.sslErrorsOccurred.connect(pending_dialog, Qt.ConnectionType.DirectConnection)
                started = time.monotonic()
                try:
                    with self.assertRaises(TransportError):
                        QgisTransport().request("GET", f"https://localhost:{secure.server_port}", timeout=0.1)
                    self.assertLess(time.monotonic() - started, 0.4)
                finally:
                    manager.sslErrorsOccurred.disconnect(pending_dialog)
            self.in_task(operation)
            self.assertEqual(prompts, [], "Background requests must never wait for a TLS dialog")
            self.assertEqual(secure.received, [])
            from qgis.core import QgsAuthCertUtils, QgsAuthConfigSslServer
            from qgis.PyQt.QtNetwork import QSslCertificate, QSslError
            certificate_object = QSslCertificate.fromPath(str(certificate))[0]
            config = QgsAuthConfigSslServer()
            config.setSslCertificate(certificate_object)
            host_port = f"localhost:{secure.server_port}"
            config.setSslHostPort(host_port)
            config.setSslIgnoredErrorEnums([QSslError.SslError.SelfSignedCertificate])
            manager = QgsApplication.authManager()
            self.assertTrue(manager.storeSslCertCustomConfig(config))
            try:
                response = self.in_task(lambda _task: QgisTransport().request(
                    "GET", "https://" + host_port, timeout=1))
                self.assertEqual(response.status_code, 200)
                # The saved exception does not disable verification on another host.
                with self.assertRaises(TransportError):
                    self.in_task(lambda _task: QgisTransport().request(
                        "GET", f"https://127.0.0.1:{secure.server_port}", timeout=1))
            finally:
                manager.removeSslCertCustomConfig(
                    QgsAuthCertUtils.shaHexForCert(certificate_object), host_port)
        finally:
            secure.shutdown()
            secure.server_close()

    def test_http_proxy_uses_qgis_profile_settings_without_global_timeout_changes(self):
        from qgis.core import Qgis, QgsNetworkAccessManager, QgsSettings, QgsSettingsTree
        from qgis.PyQt.QtNetwork import QNetworkProxy
        from geodel.qgis_transport import QgisTransport

        settings = QgsSettings()
        values = {
            "proxyEnabled": True, "proxyHost": "127.0.0.1",
            "proxyPort": str(self.server.server_port), "proxyType": "HttpProxy",
            "proxyUser": "fixture-user", "proxyPassword": "fixture-password",
        }
        modern_names = {"proxyEnabled": "proxy-enabled", "proxyHost": "proxy-host",
                        "proxyPort": "proxy-port", "proxyType": "proxy-type",
                        "proxyUser": "proxy-user", "proxyPassword": "proxy-password"}
        restore = []
        for name, value in values.items():
            if Qgis.QGIS_VERSION_INT >= 40000:
                entry = QgsSettingsTree.node("proxy").childSetting(modern_names[name])
                restore.append((entry, entry.value()))
                entry.setValue(value)
            else:
                key = "proxy/" + name
                restore.append((key, settings.value(key)))
                settings.setValue(key, value)
        self.server.proxy_auth = True
        original_timeout = QgsNetworkAccessManager.timeout()
        def operation(_task):
            manager = QgsNetworkAccessManager.instance()
            manager.setupDefaultProxyAndCache()
            try:
                return QgisTransport().request("GET", "http://fixture.invalid/api/v1/organizations")
            finally:
                manager.setFallbackProxyAndExcludes(
                    QNetworkProxy(QNetworkProxy.ProxyType.NoProxy), [], [])
        try:
            self.assertEqual(self.in_task(operation).status_code, 200)
            self.assertEqual(self.server.received[-1][1], "http://fixture.invalid/api/v1/organizations")
            self.assertEqual(self.server.received[-1][2]["proxy-authorization"],
                             "Basic Zml4dHVyZS11c2VyOmZpeHR1cmUtcGFzc3dvcmQ=")
            self.assertEqual(QgsNetworkAccessManager.timeout(), original_timeout)
        finally:
            for target, value in restore:
                if isinstance(target, str):
                    if value is None:
                        settings.remove(target)
                    else:
                        settings.setValue(target, value)
                else:
                    target.setValue(value)

    def test_http_errors_and_invalid_json_keep_distinct_client_failures(self):
        from geodel.client import (GeoDelClient, AuthenticationError, AuthorizationError,
                                   ServerUnavailableError, GeoDelError)
        from geodel.qgis_transport import QgisTransport
        for status, error in ((401, AuthenticationError), (403, AuthorizationError),
                              (503, ServerUnavailableError), (200, GeoDelError)):
            self.server.status = status
            self.server.body = b"invalid JSON"
            with self.assertRaises(error):
                self.in_task(lambda _task: GeoDelClient(
                    self.url, "synthetic-key", "0.1.0", QgisTransport()).list_organizations())

    def test_credentials_and_cache_policy_do_not_survive_request_scope(self):
        from geodel.qgis_transport import QgisTransport
        from qgis.core import QgsBlockingNetworkRequest
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtNetwork import QNetworkRequest
        def operation(_task):
            transport = QgisTransport()
            transport.request("GET", self.url + "/authenticated", headers={
                "Authorization": "Bearer synthetic-key", "X-Organization-Id": "org-1"})
            transport.request("PUT", self.url + "/storage", data=b"bytes")
            # Unrelated native requests keep their own header values after scope ends.
            request = QNetworkRequest(QUrl(self.url + "/unrelated"))
            request.setRawHeader(b"Authorization", b"Bearer other-plugin-key")
            QgsBlockingNetworkRequest().get(request, True)
        self.in_task(operation)
        self.assertNotIn("authorization", self.server.received[1][2])
        self.assertEqual(self.server.received[2][2]["authorization"], "Bearer other-plugin-key")

    def test_native_multipart_upload_failure_and_cancellation_attempt_cleanup(self):
        import os
        from pathlib import Path
        from qgis.PyQt.QtCore import QTimer
        from geodel.client import GeoDelClient, GeoDelError, UploadCanceled
        from geodel.qgis_transport import QgisTransport

        source = Path(os.environ["GEODEL_RUNTIME_ROOT"]) / "roads.geojson"
        source.write_bytes(b'{"type":"FeatureCollection","features":[]}')
        def route(method, path):
            if method == "DELETE":
                return 200, b'{}'
            if path == "/api/v1/uploads/s3/multipart":
                return 200, b'{"uploadId":"attempt-1","key":"storage-key"}'
            if path.startswith("/api/v1/uploads/s3/multipart/attempt-1/1"):
                return 200, json.dumps({"url": self.url + storage_path}).encode()
            return 503, b'{"message":"storage unavailable"}'
        self.server.route = route
        for storage_path, expected in (("/part", GeoDelError), ("/slow", UploadCanceled)):
            self.server.received.clear()
            self.server.started.clear()
            tasks = []
            def operation(task):
                tasks.append(task)
                client = GeoDelClient(self.url, "synthetic-key", "0.1.0", QgisTransport(), task.isCanceled)
                with self.assertRaises(expected):
                    client.upload_file(source, source.name, "org-1")
            timer = QTimer()
            timer.setInterval(10)
            timer.timeout.connect(lambda: tasks[0].cancel() if tasks and self.server.started.is_set() else None)
            timer.start()
            try:
                self.in_task(operation)
            finally:
                timer.stop()
                timer.timeout.disconnect()
            self.assertEqual(self.server.received[-1][0], "DELETE")
            self.assertEqual(self.server.received[-1][1],
                             "/api/v1/uploads/s3/multipart/attempt-1?key=storage-key")
            self.assertEqual(self.server.received[-1][2]["authorization"], "Bearer synthetic-key")
            self.assertNotIn("authorization", self.server.received[2][2])
            self.assertEqual(self.server.received[2][3], source.read_bytes())

    def test_module_reload_keeps_single_network_policy_registration(self):
        import importlib
        from unittest.mock import patch
        from qgis.core import QgsNetworkAccessManager
        import geodel.qgis_transport as module
        old_transport = module.QgisTransport()
        original = QgsNetworkAccessManager.setRequestPreprocessor
        original_reply = QgsNetworkAccessManager.setReplyPreprocessor
        with patch.object(QgsNetworkAccessManager, "setRequestPreprocessor", wraps=original) as register, \
                patch.object(QgsNetworkAccessManager, "setReplyPreprocessor", wraps=original_reply) as register_reply:
            for _ in range(3):
                sys.modules.pop("geodel.qgis_transport")
                module = importlib.import_module("geodel.qgis_transport")
            self.assertEqual(register.call_count, 0)
            self.assertEqual(register_reply.call_count, 0)
        self.in_task(lambda _task: old_transport.request("DELETE", self.url + "/old-cleanup",
                                                       headers={"Authorization": "Bearer synthetic-key"}))
        self.server.redirect_url = "/destination"
        self.in_task(lambda _task: module.QgisTransport().request(
            "GET", self.url + "/redirect", headers={"Authorization": "Bearer synthetic-key"}))
        self.assertEqual(self.server.received[-1][2]["authorization"], "Bearer synthetic-key")

    def test_cached_origin_credentials_survive_geodel_without_reaching_storage(self):
        from qgis.core import QgsBlockingNetworkRequest, QgsNetworkAccessManager
        from qgis.PyQt.QtCore import QUrl, Qt
        from qgis.PyQt.QtNetwork import QNetworkRequest
        from geodel.qgis_transport import QgisTransport
        self.server.auth_challenge = True
        def operation(_task):
            manager = QgsNetworkAccessManager.instance()
            def authorize(_reply, authenticator):
                authenticator.setUser("fixture-user")
                authenticator.setPassword("synthetic-key")
            manager.authenticationRequired.connect(authorize, Qt.ConnectionType.DirectConnection)
            try:
                seed = QgsBlockingNetworkRequest()
                seed.get(QNetworkRequest(QUrl(self.url)), True)
                self.assertEqual(seed.reply().attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute), 200)
            finally:
                manager.authenticationRequired.disconnect(authorize)
            prompts = []
            def unexpected_prompt(*_args):
                prompts.append(True)
                time.sleep(0.5)
            manager.requestRequiresAuth.connect(unexpected_prompt, Qt.ConnectionType.DirectConnection)
            started = time.monotonic()
            try:
                response = QgisTransport().request("PUT", self.url + "/storage", data=b"bytes", timeout=0.1)
                self.assertEqual(response.status_code, 401)
                self.assertLess(time.monotonic() - started, 0.4)
                self.assertFalse(manager.signalsBlocked())
                self.assertEqual(prompts, [])
                # A later provider request on this same pool thread must still
                # reuse its seeded credentials without another auth challenge.
                received = len(self.server.received)
                unrelated = QgsBlockingNetworkRequest()
                # Make a regression return 401 instead of opening a modal login
                # dialog if GeoDel has accidentally evicted the cached password.
                previous = manager.blockSignals(True)
                try:
                    unrelated.get(QNetworkRequest(QUrl(self.url + "/unrelated")), True)
                finally:
                    manager.blockSignals(previous)
                self.assertEqual(unrelated.reply().attribute(
                    QNetworkRequest.Attribute.HttpStatusCodeAttribute), 200)
                self.assertEqual(len(self.server.received), received + 1)
                self.assertEqual(prompts, [])
            finally:
                manager.requestRequiresAuth.disconnect(unexpected_prompt)
        self.in_task(operation)
        self.assertIn("authorization", self.server.received[-3][2])
        self.assertNotIn("authorization", self.server.received[-2][2])
        self.assertIn("authorization", self.server.received[-1][2])
