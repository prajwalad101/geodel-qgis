from pathlib import Path

from qgis.PyQt.QtCore import QTimer, Qt
from qgis.PyQt.QtGui import QIcon
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:  # Qt5 places QAction in QtWidgets.
    from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtWidgets import QFileDialog, QListWidgetItem, QMessageBox
from qgis.core import (
    Qgis, QgsApplication, QgsAuthMethodConfig, QgsIconUtils, QgsMessageLog,
    QgsProject, QgsSettings, QgsTask, QgsVectorLayer,
)

from .client import (
    AuthenticationError, GeoDelError,
    ServerUnavailableError,
)
from .auth_compat import unpack_auth_result
from .config import API_URL, DEFAULT_CONFIG, PRODUCT_NAME
from .dock import GeoDelDockWidget
from .layer_export import LayerExport
from .task_lifecycle import cancel_task, disconnect_signal, task_is_active
from .tasks import (
    _load_organizations, _load_metadata, _load_folders, _load_recent_uploads,
    _upload_file,
)

SETTINGS_PREFIX = "GeoDel"
METADATA_REFRESH_MILLISECONDS = 5 * 60 * 1000
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


class GeoDelPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.settings = QgsSettings()
        self.action = None
        self.dock = None
        self._organization_task = None
        self._organization_timer = None
        self._organization_version = 0
        self._folder_task = None
        self._upload_task = None
        self._upload_cancel_requested = False
        self._uploads_task = None
        self._version_task = None
        self._metadata_timer = None
        self._config = DEFAULT_CONFIG
        self._recent_timer = None
        self._selected_path = None
        self._candidate_api_key = None
        self._connection_valid = False
        self._connection_version = 0
        self._lifecycle_version = 0
        self._signals = []
        self._upload_progress = None

    def initGui(self):  # noqa: N802 - QGIS plugin API
        if self.action is not None:
            return
        self._lifecycle_version += 1
        icon = QIcon(str(Path(__file__).with_name("icon.png")))
        self.action = QAction(icon, PRODUCT_NAME, self.iface.mainWindow())
        self.action.setObjectName("GeoDelAction")
        self.action.setCheckable(True)
        self.action.setToolTip(f"Open {PRODUCT_NAME}")
        self._connect(self.action.triggered, self._toggle_panel, with_arguments=True)
        self.iface.addPluginToWebMenu(PRODUCT_NAME, self.action)
        self.iface.addWebToolBarIcon(self.action)

        self.dock = GeoDelDockWidget(self.iface.mainWindow())
        self._connect(self.dock.refresh_requested, self._refresh_connection)
        self._connect(self.dock.connect_requested, self._save_and_connect)
        self._connect(self.dock.manage_requested, self._manage_connection)
        self._connect(self.dock.return_requested, self._return_to_main)
        self.dock.show_setup()
        self._connect(self.dock.organizations.currentIndexChanged, self._organization_changed)
        self._connect(self.dock.folders.currentIndexChanged, self._folder_changed)
        self._connect(self.dock.layers.itemSelectionChanged, self._layers_changed)
        self._connect(self.dock.browse_button.clicked, self._browse_file)
        self._connect(self.dock.browse_button.file_dropped, self._choose_file, with_arguments=True)
        self._connect(
            self.dock.source_layers_button.clicked, lambda: self._source_changed(False),
        )
        self._connect(
            self.dock.source_file_button.clicked, lambda: self._source_changed(True),
        )
        self._connect(self.dock.upload_name.textChanged, self._update_upload_enabled)
        self._connect(self.dock.upload_button.clicked, self._start_upload)
        self._connect(self.dock.cancel_upload_button.clicked, self._cancel_upload)
        self._connect(self.dock.visibilityChanged, self._panel_visibility_changed, with_arguments=True)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.dock.hide()
        self._recent_timer = QTimer(self.dock)
        self._recent_timer.setInterval(self._config.recent_uploads_refresh_seconds * 1000)
        self._connect(self._recent_timer.timeout, self._refresh_recent_uploads)
        self._organization_timer = QTimer(self.dock)
        self._organization_timer.setSingleShot(True)
        self._organization_timer.setInterval(self._config.connection_feedback_timeout_seconds * 1000)
        self._connect(self._organization_timer.timeout, self._organization_timed_out)
        self._metadata_timer = QTimer(self.dock)
        self._metadata_timer.setInterval(METADATA_REFRESH_MILLISECONDS)
        self._connect(self._metadata_timer.timeout, self._check_version)
        self.dock.browse_button.set_config(self._config)
        project = QgsProject.instance()
        self._connect(project.layersAdded, self._refresh_layers)
        self._connect(project.layersRemoved, self._refresh_layers)
        self._connect(project.cleared, self._refresh_layers)
        self._refresh_layers()
        self._check_version()

    def _connect(self, signal, callback, with_arguments=False):
        version = self._lifecycle_version

        def guarded(*args):
            # Disconnecting does not retract already queued Qt signal deliveries.
            if version == self._lifecycle_version:
                callback(*args) if with_arguments else callback()

        signal.connect(guarded)
        self._signals.append((signal, guarded))

    def unload(self):
        self._lifecycle_version += 1
        # Detach callbacks before removal: hiding a dock emits visibilityChanged.
        for signal, callback in self._signals:
            disconnect_signal(signal, callback)
        self._signals.clear()
        self._disconnect_upload_progress()
        for name in ("_recent_timer", "_organization_timer", "_metadata_timer"):
            timer = getattr(self, name)
            if timer is not None:
                timer.stop()
                timer.deleteLater()
                setattr(self, name, None)
        for name in (
            "_organization_task", "_folder_task", "_upload_task",
            "_uploads_task", "_version_task",
        ):
            task = getattr(self, name)
            # Invalidate first, so canceled/queued completions cannot touch UI.
            setattr(self, name, None)
            cancel_task(task)
        self._candidate_api_key = None
        self._selected_path = None
        self._connection_valid = False
        if self.action is not None:
            self.iface.removePluginWebMenu(PRODUCT_NAME, self.action)
            self.iface.removeWebToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None
        if self.dock is not None:
            for timer in self.dock.findChildren(QTimer):
                timer.stop()
            self.dock.api_key.clear()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

    def _toggle_panel(self, visible):
        if self.dock is not None:
            self.dock.setVisible(visible)

    def _panel_visibility_changed(self, visible):
        if self.action:
            self.action.setChecked(visible)
        if visible:
            self._check_version()
            self._refresh_layers()
            self._refresh_organizations()
            if self._recent_timer:
                self._recent_timer.start()
            if self._metadata_timer:
                self._metadata_timer.start()
        else:
            if self._recent_timer:
                self._recent_timer.stop()
            if self._metadata_timer:
                self._metadata_timer.stop()
            cancel_task(self._uploads_task)
            self._uploads_task = None

    def _check_version(self):
        if self.dock is None or self._version_task is not None:
            return
        task: QgsTask = QgsTask.fromFunction(
            f"Load {PRODUCT_NAME} plugin metadata",
            _load_metadata,
            on_finished=lambda error, result=None: self._version_checked(
                task, error, result
            ),
            server_url=API_URL,
            config=self._config,
        )
        self._version_task = task
        QgsApplication.taskManager().addTask(task)

    def _version_checked(self, task, error, metadata):
        if task is not self._version_task:
            return
        self._version_task = None
        if self.dock is None:
            return
        if error is not None:
            QgsMessageLog.logMessage(
                "Could not load plugin metadata; retaining current settings.",
                PRODUCT_NAME, Qgis.MessageLevel.Warning,
            )
            return
        if metadata is None:
            return
        requires_update, config, config_error = metadata
        if config_error:
            QgsMessageLog.logMessage(
                "Invalid plugin configuration; retaining current settings.",
                PRODUCT_NAME, Qgis.MessageLevel.Warning,
            )
        if config is not None:
            self._config = config
            self.dock.browse_button.set_config(config)
            self._recent_timer.setInterval(config.recent_uploads_refresh_seconds * 1000)
            self._organization_timer.setInterval(config.connection_feedback_timeout_seconds * 1000)
            self._update_upload_enabled()
        was_visible = not self.dock.update_notice.isHidden()
        self.dock.update_notice.setVisible(requires_update)
        if requires_update and not was_visible:
            self.iface.messageBar().pushWarning(
                PRODUCT_NAME,
                f"Please update the {PRODUCT_NAME} plugin to continue.",
            )

    def _refresh_connection(self):
        self._check_version()
        self._refresh_organizations()

    def _refresh_organizations(self):
        if self.dock is None:
            return
        cancel_task(self._organization_task)
        self._candidate_api_key = None
        api_key = self._load_api_key()
        if not api_key:
            self._organization_task = None
            self.dock.set_loading(False)
            self.dock.organizations.clear()
            self._connection_valid = False
            self.dock.show_setup(self.dock.setup_status.text())
            return

        if self.dock.screens.currentWidget() is self.dock.setup_panel:
            self.dock.show_connecting(
                "Checking saved Personal API Key…",
                allow_cancel=self._connection_valid,
            )
        self.dock.set_loading(True)
        self._start_organization_request(api_key)

    def _start_organization_request(self, api_key):
        version = self._connection_version
        task: QgsTask = QgsTask.fromFunction(
            f"Load {PRODUCT_NAME} workspaces",
            _load_organizations,
            on_finished=lambda error, result=None: self._organizations_loaded(
                task, version, error, result
            ),
            server_url=API_URL,
            api_key=api_key,
            config=self._config,
        )
        self._organization_task = task
        self._organization_version = version
        if self._organization_timer:
            self._organization_timer.start()
        QgsApplication.taskManager().addTask(task)

    def _organization_timed_out(self):
        # Bound connection feedback even when its task has not started.
        task = self._organization_task
        if task is None:
            return
        cancel_task(task)
        self._organizations_loaded(
            task,
            self._organization_version,
            ServerUnavailableError("Connection check timed out"),
            None,
        )

    def _save_and_connect(self):
        if self.dock is None:
            return
        api_key = self.dock.api_key.text().strip()
        if not api_key:
            self.dock.setup_status.setText("Paste a Personal API Key.")
            return
        cancel_task(self._organization_task)
        self._candidate_api_key = api_key
        self.dock.show_connecting(allow_cancel=self._connection_valid)
        self._start_organization_request(api_key)

    def _manage_connection(self):
        if self.dock is None:
            return
        cancel_task(self._organization_task)
        self._organization_task = None
        self.dock.set_loading(False)
        self.dock.show_setup(allow_cancel=True)

    def _return_to_main(self):
        if self.dock is None:
            return
        cancel_task(self._organization_task)
        self._organization_task = None
        self._candidate_api_key = None
        self.dock.set_loading(False)
        self.dock.show_connected()

    def _connection_rejected(self, version):
        if self.dock is None:
            return
        if version != self._connection_version:
            return
        self._connection_valid = False
        self._candidate_api_key = None
        auth_config_id = self.settings.value(
            f"{SETTINGS_PREFIX}/authConfigId", "", type=str
        )
        if auth_config_id:
            QgsApplication.authManager().removeAuthenticationConfig(auth_config_id)
        self.settings.remove(f"{SETTINGS_PREFIX}/authConfigId")
        self.dock.organizations.clear()
        self.dock.show_setup(SAVED_KEY_REJECTED_MESSAGE)

    def _organizations_loaded(self, task, version, error, organizations):
        if task is not self._organization_task:
            return
        self._organization_task = None
        if self._organization_timer:
            self._organization_timer.stop()
        if self.dock is None:
            return
        if error is not None:
            QgsMessageLog.logMessage(
                f"Connection check failed: {error}",
                PRODUCT_NAME,
                Qgis.MessageLevel.Warning,
            )
        managing = (
            self._connection_valid
            and self.dock.screens.currentWidget() is self.dock.setup_panel
        )
        candidate_api_key = self._candidate_api_key
        self._candidate_api_key = None
        self.dock.set_loading(False)
        if isinstance(error, AuthenticationError):
            if candidate_api_key:
                self.dock.show_setup(
                    NEW_KEY_REJECTED_MESSAGE, allow_cancel=self._connection_valid
                )
            else:
                self._connection_rejected(version)
        elif error is not None:
            message = (
                SERVER_UNAVAILABLE_MESSAGE
                if isinstance(error, ServerUnavailableError)
                else CONNECTION_FAILED_MESSAGE
            )
            if candidate_api_key:
                self.dock.show_setup(message, allow_cancel=self._connection_valid)
            elif self._connection_valid:
                if managing:
                    self.dock.show_setup(message, allow_cancel=True)
                else:
                    self.dock.show_connected()
                    self.dock.status.setText(f"Connection preserved. {message}")
            else:
                self.dock.show_setup(message)
                self.dock.retry_connection_button.show()
        elif organizations is None:
            message = "Connection check was canceled. Try again."
            if candidate_api_key:
                self.dock.show_setup(message, allow_cancel=self._connection_valid)
            elif self._connection_valid:
                if managing:
                    self.dock.show_setup(message, allow_cancel=True)
                else:
                    self.dock.show_connected()
                    self.dock.status.setText(message)
            else:
                self.dock.show_setup(message)
                self.dock.retry_connection_button.show()
        else:
            if candidate_api_key and not self._store_api_key(candidate_api_key):
                self.dock.show_setup(
                    f"{PRODUCT_NAME} accepted this key, but QGIS could not save "
                    "it securely.",
                    allow_cancel=self._connection_valid,
                )
                return
            self.dock.api_key.clear()
            self._connection_valid = True
            if not organizations:
                self.dock.show_organization_setup()
                return
            if managing and not candidate_api_key:
                self.dock.show_setup("Connection verified.", allow_cancel=True)
            else:
                self.dock.show_connected()
            self.dock.set_organizations(
                organizations,
                self.settings.value(
                    f"{SETTINGS_PREFIX}/lastOrganizationId", "", type=str
                ),
            )
            # set_organizations blocks signals, so load folders/uploads here.
            self._organization_changed()

    def _organization_changed(self):
        if self.dock is None:
            return
        organization_id = self.dock.organizations.currentData() or ""
        self.settings.setValue(f"{SETTINGS_PREFIX}/lastOrganizationId", organization_id)
        # Drop previous org's in-flight poll and rows so nothing leaks across orgs.
        cancel_task(self._uploads_task)
        self._uploads_task = None
        self.dock.set_recent_uploads([])
        self._refresh_folders()
        self._refresh_recent_uploads()
        self._update_upload_enabled()

    def _refresh_recent_uploads(self):
        if self.dock is None or not self.dock.isVisible():
            return
        if task_is_active(self._uploads_task):
            return
        organization_id = self.dock.organizations.currentData()
        api_key = self._load_api_key()
        if not organization_id or not api_key:
            self._uploads_task = None
            self.dock.set_recent_uploads([])
            self.dock.recent_status.setText(
                "Choose a workspace to load recent uploads."
            )
            return

        server_url = API_URL
        if self.dock.recent_uploads.count() == 0:
            self.dock.recent_status.setText("Loading recent uploads…")
        version = self._connection_version
        task: QgsTask = QgsTask.fromFunction(
            f"Load recent {PRODUCT_NAME} uploads",
            _load_recent_uploads,
            on_finished=lambda error, result=None: self._recent_uploads_loaded(
                task, version, organization_id, error, result
            ),
            server_url=server_url,
            api_key=api_key,
            organization_id=organization_id,
            config=self._config,
        )
        self._uploads_task = task
        QgsApplication.taskManager().addTask(task)

    def _recent_uploads_loaded(self, task, version, organization_id, error, uploads):
        if task is not self._uploads_task:
            return
        self._uploads_task = None
        if (
            self.dock is None
            or organization_id != self.dock.organizations.currentData()
        ):
            return
        if error is not None:
            if isinstance(error, AuthenticationError):
                self._connection_rejected(version)
                return
            self.dock.recent_status.setText(
                str(error)
                if isinstance(error, GeoDelError)
                else "Could not load recent uploads."
            )
        elif uploads is not None:
            self.dock.set_recent_uploads(uploads)

    def _refresh_folders(self):
        cancel_task(self._folder_task)
        if self.dock is None:
            self._folder_task = None
            return
        self.dock.set_folders([])
        self.dock.folders.setEnabled(False)
        self.dock.upload_button.setEnabled(False)
        organization_id = self.dock.organizations.currentData()
        api_key = self._load_api_key()
        if not organization_id or not api_key:
            self._folder_task = None
            self.dock.set_folders([])
            return

        version = self._connection_version
        task: QgsTask = QgsTask.fromFunction(
            f"Load {PRODUCT_NAME} folders",
            _load_folders,
            on_finished=lambda error, result=None: self._folders_loaded(
                task, version, organization_id, error, result
            ),
            server_url=API_URL,
            api_key=api_key,
            organization_id=organization_id,
            config=self._config,
        )
        self._folder_task = task
        QgsApplication.taskManager().addTask(task)

    def _folders_loaded(self, task, version, organization_id, error, folders):
        if task is not self._folder_task:
            return
        self._folder_task = None
        if (
            self.dock is None
            or organization_id != self.dock.organizations.currentData()
        ):
            return
        self.dock.folders.setEnabled(True)
        if error is not None:
            if isinstance(error, AuthenticationError):
                self._connection_rejected(version)
                return
            self.dock.set_folders([])
            self.dock.status.setText(
                str(error)
                if isinstance(error, GeoDelError)
                else "Could not load folders."
            )
            self._update_upload_enabled()
            return
        if folders is None:
            self._update_upload_enabled()
            return
        self.dock.set_folders(
            folders,
            self.settings.value(
                f"{SETTINGS_PREFIX}/lastFolderId/{organization_id}", "", type=str
            ),
        )
        self._update_upload_enabled()

    def _folder_changed(self):
        if self.dock is None:
            return
        organization_id = self.dock.organizations.currentData()
        if organization_id:
            self.settings.setValue(
                f"{SETTINGS_PREFIX}/lastFolderId/{organization_id}",
                self.dock.folders.currentData() or "",
            )

    def _refresh_layers(self, *_args):
        if self.dock is None:
            return
        selected_ids = {
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.dock.layers.selectedItems()
        }
        layers = sorted(
            (
                layer
                for layer in QgsProject.instance().mapLayers().values()
                if isinstance(layer, QgsVectorLayer)
            ),
            key=lambda layer: layer.name().casefold(),
        )
        self.dock.layers.blockSignals(True)
        self.dock.layers.clear()
        remaining_ids = set()
        for layer in layers:
            item = QListWidgetItem(QgsIconUtils.iconForLayer(layer), layer.name())
            item.setData(Qt.ItemDataRole.UserRole, layer.id())
            self.dock.layers.addItem(item)
            if layer.id() in selected_ids:
                item.setSelected(True)
                remaining_ids.add(layer.id())
        self.dock.layers.blockSignals(False)
        if remaining_ids != selected_ids:
            self._layers_changed()
        self._update_upload_enabled()

    def _selected_layers(self):
        if self.dock is None:
            return []
        project = QgsProject.instance()
        layers = []
        for item in self.dock.layers.selectedItems():
            layer = project.mapLayer(item.data(Qt.ItemDataRole.UserRole))
            if isinstance(layer, QgsVectorLayer):
                layers.append(layer)
        return layers

    def _layers_changed(self):
        if self.dock is None:
            return
        layers = self._selected_layers()
        if layers:
            self._selected_path = None
            self.dock.file_path.clear()
            self.dock.file_path.setToolTip("")
            project = QgsProject.instance()
            name = (
                layers[0].name()
                if len(layers) == 1
                else project.title() or project.baseName() or "QGIS project"
            )
            self.dock.upload_name.setText(name)
            self.dock.status.clear()
            self.dock.show_source(False)
        elif self._selected_path is None:
            self.dock.upload_name.clear()
        self._update_upload_enabled()

    def _browse_file(self):
        if not self._config.allowed_extensions:
            self.iface.messageBar().pushCritical(PRODUCT_NAME, "No supported upload formats are available.")
            return
        start = self.settings.value(f"{SETTINGS_PREFIX}/lastDirectory", "", type=str)
        filename, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            "Choose a file to share",
            start,
            f"Supported files ({' '.join('*' + extension for extension in self._config.allowed_extensions)})",
        )
        if filename:
            self._choose_file(filename)

    def _choose_file(self, filename):
        if self.dock is None:
            return
        path = Path(filename)
        if path.suffix.lower() not in self._config.allowed_extensions:
            self.iface.messageBar().pushCritical(
                PRODUCT_NAME, f"Supported upload formats are {self._config.extensions_label}."
            )
            return
        self._selected_path = path
        self.dock.layers.blockSignals(True)
        self.dock.layers.clearSelection()
        self.dock.layers.blockSignals(False)
        self.settings.setValue(f"{SETTINGS_PREFIX}/lastDirectory", str(path.parent))
        self.dock.file_path.setText(path.name)
        self.dock.file_path.setToolTip(str(path))
        self.dock.upload_name.setText(path.stem)
        self.dock.status.clear()
        self.dock.show_source(True)
        self._update_upload_enabled()

    def _source_changed(self, use_file):
        if self.dock is None:
            return
        self.dock.show_source(use_file)
        if use_file:
            # Emits itemSelectionChanged -> _layers_changed resets the name.
            self.dock.layers.clearSelection()
            return
        self._selected_path = None
        self.dock.file_path.clear()
        self.dock.file_path.setToolTip("")
        self._layers_changed()

    def _update_upload_enabled(self):
        if (
            self.dock is None
            or self._upload_task is not None
            or self._folder_task is not None
        ):
            return
        self.dock.upload_button.setEnabled(
            (self._selected_path is not None or bool(self._selected_layers()))
            and bool(self._config.allowed_extensions)
            and bool(self.dock.organizations.currentData())
            and bool(self.dock.upload_name.text().strip())
        )

    def _upload_filename(self, suffix):
        if self.dock is None:
            return
        name = self.dock.upload_name.text().strip()
        if not name or "/" in name or "\\" in name:
            self.iface.messageBar().pushCritical(
                PRODUCT_NAME, "Upload name cannot be empty or contain slashes."
            )
            return None
        filename = name if name.lower().endswith(suffix) else f"{name}{suffix}"
        try:
            self._config.validate_filename(filename)
        except ValueError as error:
            self.iface.messageBar().pushCritical(PRODUCT_NAME, str(error))
            return None
        return filename

    def _upload_destination(self):
        if self.dock is None:
            return
        organization_id = self.dock.organizations.currentData()
        api_key = self._load_api_key()
        if not organization_id or not api_key:
            self.iface.messageBar().pushCritical(
                PRODUCT_NAME, "Choose a workspace and configure an API key."
            )
            return None
        return {
            "server_url": API_URL,
            "api_key": api_key,
            "organization_id": organization_id,
            "folder_id": self.dock.folders.currentData() or None,
            "config": self._config,
        }

    def _new_upload_task(
        self,
        path,
        upload_filename,
        destination,
        version,
        artifact=None,
    ):
        task: QgsTask = QgsTask.fromFunction(
            f"Upload {upload_filename} to {PRODUCT_NAME}",
            _upload_file,
            on_finished=lambda error, result=None: self._upload_finished(
                task, version, destination["server_url"], error, result
            ),
            path=str(path) if path else None,
            upload_filename=upload_filename,
            artifact=artifact,
            **destination,
        )
        return task

    def _disconnect_upload_progress(self):
        if self._upload_progress is not None:
            disconnect_signal(*self._upload_progress)
            self._upload_progress = None

    def _run_upload_task(self, task, exporting=False):
        if self.dock is None:
            cancel_task(task)
            return
        self._disconnect_upload_progress()
        self._upload_task = task
        self._upload_cancel_requested = False
        self.dock.set_uploading(True)
        if exporting:
            self.dock.upload_button.setText("Preparing layers…")

        def show_progress(value):
            # Queued signal: may arrive after unload() or after a newer task started.
            if self.dock is not None and task is self._upload_task:
                self.dock.progress.setValue(int(value))

        task.progressChanged.connect(show_progress)
        self._upload_progress = (task.progressChanged, show_progress)
        QgsApplication.taskManager().addTask(task)

    def _cancel_upload(self):
        if (
            self.dock is None or self._upload_task is None
            or self._upload_cancel_requested
        ):
            return
        self._upload_cancel_requested = True
        self.dock.cancel_upload_button.setEnabled(False)
        self.dock.cancel_upload_button.setText("Canceling…")
        self.dock.status.setText("Canceling upload…")
        cancel_task(self._upload_task)

    def _start_upload(self):
        if self._upload_task is not None:
            return
        layers = self._selected_layers()
        if layers:
            self._start_layer_upload(layers)
            return
        if self._selected_path is None:
            return
        try:
            file_size = self._selected_path.stat().st_size
        except OSError as error:
            self.iface.messageBar().pushCritical(
                PRODUCT_NAME, f"Could not read upload file: {error}"
            )
            return
        if file_size > self._config.max_file_size_bytes:
            self.iface.messageBar().pushCritical(
                PRODUCT_NAME, f"File exceeds the {self._config.file_size_label} upload limit."
            )
            return
        if file_size == 0:
            self.iface.messageBar().pushCritical(PRODUCT_NAME, "File is empty.")
            return

        upload_filename = self._upload_filename(self._selected_path.suffix.lower())
        if upload_filename is None:
            return
        destination = self._upload_destination()
        if destination is None:
            return
        self._run_upload_task(
            self._new_upload_task(
                self._selected_path,
                upload_filename,
                destination,
                self._connection_version,
            )
        )

    def _start_layer_upload(self, layers):
        try:
            export = LayerExport(layers, self._config)
        except GeoDelError as error:
            self.iface.messageBar().pushCritical(PRODUCT_NAME, str(error))
            return
        upload_filename = self._upload_filename(export.suffix)
        if upload_filename is None:
            return
        destination = self._upload_destination()
        if destination is None:
            return

        self._run_upload_task(
            self._new_layer_export_task(export, self._connection_version, upload_filename, destination),
            exporting=True,
        )

    def _new_layer_export_task(self, export, version, upload_filename, destination):
        task: QgsTask = export.create_task(
            lambda error, artifact: self._layer_export_finished(
                task, version, upload_filename, destination, error, artifact, export
            )
        )
        return task

    def _layer_export_finished(
        self, task, version, upload_filename, destination, error, artifact, export=None
    ):
        if task is not self._upload_task:
            if artifact:
                artifact.cleanup()
            return
        if self._upload_cancel_requested:
            if artifact:
                artifact.cleanup()
            self._upload_finished(
                task, version, destination["server_url"], None, None
            )
            return
        if error is not None:
            self._upload_finished(
                task, version, destination["server_url"], error, None
            )
            return
        if artifact is None:
            self._upload_finished(
                task, version, destination["server_url"], None, None
            )
            return
        if export is not None and export.has_more_layers:
            self._run_upload_task(
                self._new_layer_export_task(export, version, upload_filename, destination),
                exporting=True,
            )
            return
        self._run_upload_task(
            self._new_upload_task(
                None, upload_filename, destination, version, artifact=artifact
            )
        )

    def _upload_finished(self, task, version, server_url, error, result):
        if task is not self._upload_task:
            return
        self._disconnect_upload_progress()
        if self._upload_cancel_requested and result is None:
            error = None
        self._upload_task = None
        self._upload_cancel_requested = False
        if self.dock is None:
            return
        self.dock.set_uploading(False)
        self._update_upload_enabled()
        self._refresh_recent_uploads()
        if error is not None:
            if isinstance(error, AuthenticationError):
                self._connection_rejected(version)
                return
            reason = (
                str(error) if isinstance(error, GeoDelError) else "Upload failed."
            )
            self.dock.status.setText(reason)
            self.iface.messageBar().pushCritical(PRODUCT_NAME, reason)
            return
        if result is None:
            self.dock.status.setText("Upload canceled.")
            return
        # Clear the source so a second click can't re-upload the same data.
        self._selected_path = None
        self.dock.file_path.clear()
        self.dock.file_path.setToolTip("")
        self.dock.layers.clearSelection()  # -> _layers_changed clears the name
        self.dock.upload_name.clear()
        self._update_upload_enabled()
        self.dock.status.setText("Uploaded. Processing status is in Recent uploads.")

    def _ensure_auth_unlocked(self):
        manager = QgsApplication.authManager()
        if manager.masterPasswordIsSet():
            return True
        if not manager.masterPasswordHashInDatabase() and not self.settings.value(
            f"{SETTINGS_PREFIX}/masterPasswordExplained", False, type=bool
        ):
            QMessageBox.information(
                self.iface.mainWindow(),
                f"{PRODUCT_NAME} credential storage",
                f"{PRODUCT_NAME} stores your API key encrypted in QGIS Authentication "
                "Manager. QGIS will now ask you to set or enter its master password.",
            )
            self.settings.setValue(f"{SETTINGS_PREFIX}/masterPasswordExplained", True)
        return manager.setMasterPassword(True)

    def _load_api_key(self):
        auth_config_id = self.settings.value(
            f"{SETTINGS_PREFIX}/authConfigId", "", type=str
        )
        if not auth_config_id or not self._ensure_auth_unlocked():
            return ""

        config = QgsAuthMethodConfig()
        loaded, config = unpack_auth_result(
            QgsApplication.authManager().loadAuthenticationConfig(
                auth_config_id, config, True
            ),
            config,
        )
        if loaded:
            return config.config("password")
        self.settings.remove(f"{SETTINGS_PREFIX}/authConfigId")
        self._connection_valid = False
        if self.dock is not None:
            self.dock.show_setup(
                "Saved Personal API Key could not be read. Paste it again."
            )
        return ""

    def _store_api_key(self, api_key):
        if not self._ensure_auth_unlocked():
            return False

        manager = QgsApplication.authManager()
        auth_config_id = self.settings.value(
            f"{SETTINGS_PREFIX}/authConfigId", "", type=str
        )
        config = QgsAuthMethodConfig()
        overwrite = False
        if auth_config_id:
            overwrite, config = unpack_auth_result(
                manager.loadAuthenticationConfig(auth_config_id, config, True),
                config,
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
                manager.storeAuthenticationConfig(config, overwrite), config
            )
        if not stored:
            QMessageBox.warning(
                self.iface.mainWindow(),
                PRODUCT_NAME,
                "Could not save API key in QGIS Authentication Manager.",
            )
            return False

        self.settings.setValue(f"{SETTINGS_PREFIX}/authConfigId", config.id())
        self._connection_version += 1
        return True
