"""Own Workspace verification, saved credentials and connection feedback."""
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import Qgis, QgsApplication, QgsAuthMethodConfig, QgsMessageLog, QgsTask

from .auth_compat import unpack_auth_result
from .client import AuthenticationError, ServerUnavailableError
from .config import API_URL, DEFAULT_CONFIG, PRODUCT_NAME
from .task_lifecycle import cancel_task
from .tasks import _load_organizations


SETTINGS_PREFIX = "GeoDel"
SERVER_UNAVAILABLE_MESSAGE = (
    "Couldn't connect to server. If this keeps happening please contact support."
)
SAVED_KEY_REJECTED_MESSAGE = (
    "Authentication failed for your saved connection. Reconnect and try again."
)
NEW_KEY_REJECTED_MESSAGE = (
    "Authentication failed. Check your connection details and try again."
)
CONNECTION_FAILED_MESSAGE = "Couldn't connect to GeoDel. Please try again."


class WorkspaceConnection:
    def __init__(self, iface, dock, settings, on_organizations, config=DEFAULT_CONFIG):
        self._iface = iface
        self._dock = dock
        self._settings = settings
        self._on_organizations = on_organizations
        self._task = None
        self._candidate_api_key = None
        self._valid = False
        self._editing = True
        self.version = 0
        self._timer = QTimer(dock)
        self._timer.setObjectName("GeoDelConnectionTimer")
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._timed_out)
        self.set_config(config)
        dock.show_setup()

    def set_config(self, config):
        self._config = config
        self._timer.setInterval(config.connection_feedback_timeout_seconds * 1000)

    def refresh(self):
        self._cancel_check()
        api_key = self.load_api_key()
        if not api_key:
            self._valid = False
            self._editing = True
            self._dock.set_loading(False)
            self._dock.organizations.clear()
            self._dock.show_setup(self._dock.setup_status.text())
            return
        if self._editing:
            self._dock.show_connecting(
                "Checking saved Personal API Key…", allow_cancel=self._valid,
            )
        self._dock.set_loading(True)
        self._start_check(api_key)

    def connect(self, api_key):
        api_key = api_key.strip()
        if not api_key:
            self._dock.setup_status.setText("Paste a Personal API Key.")
            return
        self._cancel_check()
        self._editing = True
        self._dock.show_connecting(allow_cancel=self._valid)
        self._start_check(api_key, candidate=True)

    def manage(self):
        self._cancel_check()
        self._editing = True
        self._dock.set_loading(False)
        self._dock.show_setup(allow_cancel=self._valid)

    def return_to_main(self):
        self._cancel_check()
        self._dock.set_loading(False)
        if self._valid:
            self._editing = False
            self._dock.show_connected()

    def reject(self, version):
        if self._dock is None or version != self.version:
            return
        self._cancel_check()
        self._valid = False
        self._editing = True
        auth_config_id = self._settings.value(
            f"{SETTINGS_PREFIX}/authConfigId", "", type=str,
        )
        if auth_config_id:
            QgsApplication.authManager().removeAuthenticationConfig(auth_config_id)
        self._settings.remove(f"{SETTINGS_PREFIX}/authConfigId")
        self._dock.set_loading(False)
        self._dock.organizations.clear()
        self._dock.show_setup(SAVED_KEY_REJECTED_MESSAGE)

    def close(self):
        self._dock = None
        self._on_organizations = None
        self._cancel_check()
        self._timer.deleteLater()

    def _cancel_check(self):
        task, self._task = self._task, None
        self._candidate_api_key = None
        self._timer.stop()
        cancel_task(task)

    def _start_check(self, api_key, candidate=False):
        version = self.version
        candidate_api_key = api_key if candidate else None
        task = QgsTask.fromFunction(
            f"Load {PRODUCT_NAME} workspaces",
            _load_organizations,
            on_finished=lambda error, result=None: self._finished(
                task, version, candidate_api_key, error, result[0] if result is not None else None,
            ),
            server_url=API_URL,
            api_key=api_key,
            config=self._config,
        )
        self._task = task
        self._request_version = version
        self._candidate_api_key = candidate_api_key
        self._timer.start()
        QgsApplication.taskManager().addTask(task)

    def _timed_out(self):
        task = self._task
        if task is None:
            return
        # Finish first so synchronous cancellation cannot replace timeout feedback.
        self._finished(
            task, self._request_version, self._candidate_api_key,
            ServerUnavailableError("Connection check timed out"), None,
        )
        cancel_task(task)

    def _finished(self, task, version, candidate_api_key, error, organizations):
        if task is not self._task or self._dock is None:
            return
        self._task = None
        self._candidate_api_key = None
        self._timer.stop()
        if error is not None:
            QgsMessageLog.logMessage(
                f"Connection check failed: {error}", PRODUCT_NAME, Qgis.MessageLevel.Warning,
            )
        managing = self._valid and self._editing
        self._dock.set_loading(False)
        if isinstance(error, AuthenticationError):
            if candidate_api_key:
                self._dock.show_setup(NEW_KEY_REJECTED_MESSAGE, allow_cancel=self._valid)
            else:
                self.reject(version)
            return
        if error is not None or organizations is None:
            if isinstance(error, ServerUnavailableError):
                message = SERVER_UNAVAILABLE_MESSAGE
            elif error is not None:
                message = CONNECTION_FAILED_MESSAGE
            else:
                message = "Connection check was canceled. Try again."
            if candidate_api_key or self._editing or not self._valid:
                self._editing = True
                self._dock.show_setup(message, allow_cancel=self._valid)
                if not candidate_api_key:
                    self._dock.retry_connection_button.show()
            else:
                self._dock.show_connected()
                prefix = "Connection preserved. " if error is not None else ""
                self._dock.status.setText(f"{prefix}{message}")
            return
        if candidate_api_key and not self._store_api_key(candidate_api_key):
            if self._dock is not None:
                self._dock.show_setup(
                    f"{PRODUCT_NAME} accepted this key, but QGIS could not save it securely.",
                    allow_cancel=self._valid,
                )
            return
        if self._dock is None:
            return
        self._dock.api_key.clear()
        self._valid = True
        if not organizations:
            self._editing = True
            self._dock.set_organizations([])
            self._on_organizations()
            self._dock.show_organization_setup()
            return
        if managing and not candidate_api_key:
            self._dock.show_setup("Connection verified.", allow_cancel=True)
        else:
            self._editing = False
            self._dock.show_connected()
        self._dock.set_organizations(
            organizations,
            self._settings.value(f"{SETTINGS_PREFIX}/lastOrganizationId", "", type=str),
        )
        # Population blocks signals, so notify the plugin to load folders/uploads.
        self._on_organizations()

    def _ensure_auth_unlocked(self):
        manager = QgsApplication.authManager()
        if manager.masterPasswordIsSet():
            return True
        if not manager.masterPasswordHashInDatabase() and not self._settings.value(
            f"{SETTINGS_PREFIX}/masterPasswordExplained", False, type=bool,
        ):
            QMessageBox.information(
                self._iface.mainWindow(),
                f"{PRODUCT_NAME} credential storage",
                f"{PRODUCT_NAME} stores your API key encrypted in QGIS Authentication "
                "Manager. QGIS will now ask you to set or enter its master password.",
            )
            self._settings.setValue(f"{SETTINGS_PREFIX}/masterPasswordExplained", True)
        return manager.setMasterPassword(True)

    def load_api_key(self):
        auth_config_id = self._settings.value(
            f"{SETTINGS_PREFIX}/authConfigId", "", type=str,
        )
        if not auth_config_id or not self._ensure_auth_unlocked():
            return ""
        config = QgsAuthMethodConfig()
        loaded, config = unpack_auth_result(
            QgsApplication.authManager().loadAuthenticationConfig(auth_config_id, config, True),
            config,
        )
        if loaded:
            return config.config("password")
        self._settings.remove(f"{SETTINGS_PREFIX}/authConfigId")
        self._valid = False
        self._editing = True
        if self._dock is not None:
            self._dock.show_setup("Saved Personal API Key could not be read. Paste it again.")
        return ""

    def _store_api_key(self, api_key):
        if not self._ensure_auth_unlocked() or self._dock is None:
            return False
        manager = QgsApplication.authManager()
        auth_config_id = self._settings.value(
            f"{SETTINGS_PREFIX}/authConfigId", "", type=str,
        )
        config = QgsAuthMethodConfig()
        overwrite = False
        if auth_config_id:
            overwrite, config = unpack_auth_result(
                manager.loadAuthenticationConfig(auth_config_id, config, True), config,
            )
        if not overwrite:
            config.setName(f"{PRODUCT_NAME} API key")
            config.setMethod("Basic")
            config.setConfig("username", "geodel")
        config.setUri(API_URL)
        config.setConfig("password", api_key)
        stored = False
        if config.isValid():
            stored, config = unpack_auth_result(
                manager.storeAuthenticationConfig(config, overwrite), config,
            )
        if not stored:
            QMessageBox.warning(
                self._iface.mainWindow(), PRODUCT_NAME,
                "Could not save API key in QGIS Authentication Manager.",
            )
            return False
        self._settings.setValue(f"{SETTINGS_PREFIX}/authConfigId", config.id())
        self.version += 1
        return True
