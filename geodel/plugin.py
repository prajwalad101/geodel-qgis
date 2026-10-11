from pathlib import Path

from qgis.PyQt.QtCore import QTimer, Qt
from qgis.PyQt.QtGui import QIcon
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:  # Qt5 places QAction in QtWidgets.
    from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtWidgets import QFileDialog, QListWidgetItem
from qgis.core import (
    Qgis, QgsApplication, QgsIconUtils, QgsMessageLog,
    QgsProject, QgsSettings, QgsTask, QgsVectorLayer,
)

from .client import AuthenticationError, GeoDelError
from .connection import SETTINGS_PREFIX, WorkspaceConnection
from .config import API_URL, DEFAULT_CONFIG, PRODUCT_NAME
from .dock import GeoDelDockWidget
from .task_lifecycle import cancel_task, disconnect_signal, task_is_active
from .tasks import (
    _load_metadata, _load_folders, _load_recent_uploads,
)
from .upload import Upload

METADATA_REFRESH_MILLISECONDS = 5 * 60 * 1000


class GeoDelPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.settings = QgsSettings()
        self.action = None
        self.dock = None
        self._connection = None
        self._folder_task = None
        self._upload = None
        self._uploads_task = None
        self._version_task = None
        self._metadata_timer = None
        self._config = DEFAULT_CONFIG
        self._recent_timer = None
        self._selected_path = None
        self._lifecycle_version = 0
        self._signals = []

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
        self._connection = WorkspaceConnection(
            self.iface, self.dock, self.settings, self._organization_changed, self._config,
        )
        self._connect(self.dock.refresh_requested, self._refresh_connection)
        self._connect(
            self.dock.connect_requested,
            lambda: self._connection.connect(self.dock.api_key.text()),
        )
        self._connect(self.dock.manage_requested, self._connection.manage)
        self._connect(self.dock.return_requested, self._connection.return_to_main)
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
        if self._upload is not None:
            upload, self._upload = self._upload, None
            upload.close()
        if self._connection is not None:
            connection, self._connection = self._connection, None
            connection.close()
        for name in ("_recent_timer", "_metadata_timer"):
            timer = getattr(self, name)
            if timer is not None:
                timer.stop()
                timer.deleteLater()
                setattr(self, name, None)
        for name in (
            "_folder_task",
            "_uploads_task", "_version_task",
        ):
            task = getattr(self, name)
            # Invalidate first, so canceled/queued completions cannot touch UI.
            setattr(self, name, None)
            cancel_task(task)
        self._selected_path = None
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
            self._connection.refresh()
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
            self._connection.set_config(config)
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
        if self._connection is not None:
            self._connection.refresh()

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
        api_key = self._connection.load_api_key()
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
        version = self._connection.version
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
                self._connection.reject(version)
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
        api_key = self._connection.load_api_key()
        if not organization_id or not api_key:
            self._folder_task = None
            self.dock.set_folders([])
            return

        version = self._connection.version
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
                self._connection.reject(version)
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
            or self._upload is not None
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
        api_key = self._connection.load_api_key()
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

    def _upload_progress_changed(self, upload, preparing, value):
        if self.dock is not None and upload is self._upload:
            self.dock.upload_button.setText("Preparing layers…" if preparing else "Uploading…")
            self.dock.progress.setValue(int(value))

    def _cancel_upload(self):
        upload = self._upload
        if (
            self.dock is None or upload is None
            or not upload.cancel() or upload is not self._upload
        ):
            return
        self.dock.cancel_upload_button.setEnabled(False)
        self.dock.cancel_upload_button.setText("Canceling…")
        self.dock.status.setText("Canceling upload…")

    def _start_upload(self):
        if self._upload is not None:
            return
        layers = self._selected_layers()
        if not layers and self._selected_path is None:
            return
        try:
            upload = Upload(
                path=self._selected_path, layers=layers, config=self._config,
            )
        except GeoDelError as error:
            self.iface.messageBar().pushCritical(PRODUCT_NAME, str(error))
            return
        upload_filename = self._upload_filename(upload.suffix)
        if upload_filename is None:
            return
        destination = self._upload_destination()
        if destination is None:
            return

        self._upload = upload
        self.dock.set_uploading(True)
        upload.start(
            upload_filename, destination, self._connection.version,
            self._upload_progress_changed, self._upload_finished,
        )

    def _upload_finished(self, upload, error, result):
        if upload is not self._upload:
            return
        self._upload = None
        if self.dock is None:
            return
        self.dock.set_uploading(False)
        self._update_upload_enabled()
        self._refresh_recent_uploads()
        if error is not None:
            if isinstance(error, AuthenticationError):
                self._connection.reject(upload.connection_version)
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
