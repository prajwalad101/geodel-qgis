from configparser import ConfigParser
from pathlib import Path

from qgis.PyQt.QtCore import QSize, QTimer, QUrl, Qt, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsAuthMethodConfig,
    QgsIconUtils,
    QgsMessageLog,
    QgsProject,
    QgsSettings,
    QgsTask,
    QgsVectorLayer,
)

from .client import (
    MAX_FILE_SIZE,
    MAX_FILE_SIZE_LABEL,
    AuthenticationError,
    GeoDelClient,
    GeoDelError,
    ServerUnavailableError,
    UploadCanceled,
)
from .auth_compat import unpack_auth_result
from .config import API_URL, PRODUCT_NAME, WEB_URL
from .layer_export import LayerExport
from .task_lifecycle import cancel_task, disconnect_signal, task_is_active

_metadata = ConfigParser()
_metadata.read(Path(__file__).with_name("metadata.txt"))
PLUGIN_VERSION = _metadata["general"]["version"]
SETTINGS_PREFIX = "GeoDel"
RECENT_REFRESH_MILLISECONDS = 5_000
CONNECTION_TIMEOUT_MILLISECONDS = 5_000
SERVER_UNAVAILABLE_MESSAGE = (
    "Couldn't connect to server. If this keeps happening please contact support."
)
SAVED_KEY_REJECTED_MESSAGE = (
    "Your saved API key is no longer valid. It may have been revoked. "
    "Create a new key and connect again."
)
NEW_KEY_REJECTED_MESSAGE = (
    "This API key isn't valid. Check that you copied the whole key, "
    "or create a new one."
)
CONNECTION_FAILED_MESSAGE = "Couldn't check your API key. Please try again."


def _load_organizations(task, server_url, api_key):
    if task.isCanceled():
        return None
    organizations = GeoDelClient(
        server_url, api_key, PLUGIN_VERSION
    ).list_organizations()
    return None if task.isCanceled() else organizations


def _requires_update(task, server_url):
    if task.isCanceled():
        return None
    requires_update = GeoDelClient(server_url, "", PLUGIN_VERSION).requires_update()
    return None if task.isCanceled() else requires_update


def _load_folders(task, server_url, api_key, organization_id):
    if task.isCanceled():
        return None
    folders = GeoDelClient(server_url, api_key, PLUGIN_VERSION).list_folders(
        organization_id
    )
    return None if task.isCanceled() else folders


def _load_recent_uploads(task, server_url, api_key, organization_id):
    if task.isCanceled():
        return None
    uploads = GeoDelClient(server_url, api_key, PLUGIN_VERSION).list_recent_uploads(
        organization_id
    )
    return None if task.isCanceled() else uploads


def _upload_file(
    task,
    server_url,
    api_key,
    organization_id,
    folder_id,
    path,
    upload_filename,
    artifact=None,
):
    path = artifact.path if artifact else Path(path)
    client = GeoDelClient(server_url, api_key, PLUGIN_VERSION)
    try:
        # Stop once bytes are sent; Recent uploads polls processing -> ready.
        return client.upload_file(
            path,
            upload_filename,
            organization_id,
            folder_id,
            task.setProgress,
            task.isCanceled,
        )
    except UploadCanceled:
        return None
    finally:
        if artifact:
            artifact.cleanup()


ACCENT = "#d9532f"
MUTED = "#8b929c"
BORDER = "rgba(128, 128, 128, 0.35)"
# ponytail: rgba greys instead of palette() roles so one sheet reads on light + dark QGIS themes.
DOCK_STYLE = f"""
QLabel[role="title"] {{ font-size: 15px; font-weight: 700; }}
QLabel[role="brand"] {{ font-size: 14px; font-weight: 700; }}
QLabel[role="section"] {{
    color: {MUTED}; font-size: 11px; font-weight: 700; padding-top: 8px;
}}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="strong"] {{ font-weight: 600; }}
QLabel[role="error"] {{ color: #dc2626; }}
QLabel[role="warning"] {{ color: #d97706; }}
QLabel[role="empty"] {{
    color: {MUTED}; border: 1px dashed {BORDER}; border-radius: 8px; padding: 20px;
}}
QLabel#banner {{
    color: #d97706; font-weight: 600; padding: 8px 10px; border-radius: 6px;
    background: rgba(217, 119, 6, 0.12); border: 1px solid rgba(217, 119, 6, 0.45);
}}
QLabel[chip] {{
    border-radius: 9px; padding: 1px 8px; font-size: 11px; font-weight: 700;
}}
QLabel[chip="ready"] {{ color: #16a34a; background: rgba(22, 163, 74, 0.16); }}
QLabel[chip="failed"] {{ color: #dc2626; background: rgba(220, 38, 38, 0.16); }}
QLabel[chip="processing"] {{ color: #d97706; background: rgba(217, 119, 6, 0.16); }}
QLabel[chip="pending"] {{ color: {MUTED}; background: rgba(128, 128, 128, 0.16); }}
QLineEdit, QComboBox {{
    border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px; min-height: 18px;
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QPushButton {{
    border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 12px;
    background: rgba(128, 128, 128, 0.12);
}}
QPushButton:hover {{ background: rgba(128, 128, 128, 0.22); }}
QPushButton:disabled {{ color: {MUTED}; }}
QPushButton[variant="primary"] {{
    background: {ACCENT}; color: white; border: none; font-weight: 700; padding: 9px 12px;
}}
QPushButton[variant="primary"]:hover {{ background: #e5643f; }}
QPushButton[variant="primary"]:disabled {{
    background: rgba(217, 83, 47, 0.3); color: rgba(255, 255, 255, 0.55);
}}
QPushButton[variant="link"] {{
    background: transparent; border: none; color: {ACCENT}; padding: 2px 0; text-align: left;
}}
QToolButton {{ border: 1px solid transparent; border-radius: 6px; padding: 4px 8px; }}
QToolButton:hover {{ background: rgba(128, 128, 128, 0.2); }}
QToolButton[variant="soft"] {{ background: rgba(128, 128, 128, 0.12); }}
QToolButton[segment] {{ border: 1px solid {BORDER}; border-radius: 0; padding: 3px 10px; }}
QToolButton[segment="left"] {{ border-top-left-radius: 6px; border-bottom-left-radius: 6px; }}
QToolButton[segment="right"] {{ border-top-right-radius: 6px; border-bottom-right-radius: 6px; }}
QToolButton[segment]:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QListWidget {{ border: 1px solid {BORDER}; border-radius: 8px; padding: 4px; outline: 0; }}
QListWidget::item {{ padding: 5px; border-radius: 5px; }}
QListWidget::item:selected {{ background: rgba(217, 83, 47, 0.25); color: palette(text); }}
QScrollArea#recentList {{ border: 1px solid {BORDER}; border-radius: 8px; }}
QWidget#recentContent {{ background: transparent; }}
QFrame#recentRow {{ border-bottom: 1px solid {BORDER}; }}
QPushButton#dropZone {{
    padding: 0; border: 2px dashed {BORDER}; border-radius: 8px; background: rgba(128, 128, 128, 0.05);
}}
QPushButton#dropZone:hover, QPushButton#dropZone:focus, QPushButton#dropZone[dragging="true"] {{
    border-color: {ACCENT}; background: rgba(217, 83, 47, 0.08);
}}
QLineEdit#chosenFile {{
    border: none; background: transparent; color: {ACCENT}; font-weight: 600;
}}
QProgressBar {{
    border: none; border-radius: 3px; background: rgba(128, 128, 128, 0.2);
    max-height: 6px; min-height: 6px;
}}
QProgressBar::chunk {{ border-radius: 3px; background: {ACCENT}; }}
QScrollArea {{ border: none; background: transparent; }}
"""


def _label(text="", role=None):
    label = QLabel(text)
    if role:
        label.setProperty("role", role)
    return label


def _theme_icon(name):
    return QgsApplication.getThemeIcon(f"/{name}")


def _icon_button(icon_name, tooltip):
    button = QToolButton()
    button.setIcon(_theme_icon(icon_name))
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    return button


def _brand_row():
    logo = QLabel()
    logo.setPixmap(QIcon(str(Path(__file__).with_name("icon.svg"))).pixmap(22, 22))
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(logo)
    row.addWidget(_label(PRODUCT_NAME, "brand"))
    row.addStretch()
    return row


class FileDropZone(QPushButton):
    """Button (for keyboard + screen readers) that also accepts a dropped file."""

    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Choose a file to upload")
        self.setAccessibleDescription(
            f".zip, .geojson or .json, up to {MAX_FILE_SIZE_LABEL}"
        )

        hint = _label("Drop a file here or click to browse", "strong")
        types = _label(
            f".zip · .geojson · .json  —  up to {MAX_FILE_SIZE_LABEL}", "muted"
        )
        self.file_path = QLineEdit()
        self.file_path.setObjectName("chosenFile")
        self.file_path.setReadOnly(True)
        self.file_path.setPlaceholderText("No file selected")
        self.file_path.setAccessibleName(f"{PRODUCT_NAME} upload file")
        self.file_path.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.file_path.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.file_path.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout = QVBoxLayout()
        self.setMinimumHeight(150)
        layout.setContentsMargins(16, 24, 16, 20)
        layout.setSpacing(6)
        layout.addStretch()
        for label in (hint, types):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(label)
        layout.addSpacing(6)
        layout.addWidget(self.file_path)
        layout.addStretch()
        self.setLayout(layout)

    def dragEnterEvent(self, event):  # noqa: N802 - Qt API
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            self._set_dragging(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, _event):  # noqa: N802 - Qt API
        self._set_dragging(False)

    def dropEvent(self, event):  # noqa: N802 - Qt API
        self._set_dragging(False)
        self.file_dropped.emit(event.mimeData().urls()[0].toLocalFile())

    def _set_dragging(self, dragging):
        self.setProperty("dragging", dragging)
        self.style().unpolish(self)
        self.style().polish(self)


ROW_BUTTON_HEIGHT = 28


class RecentUploadsList(QScrollArea):
    """Scrollable rows sized by a real layout, unlike QListWidget item hints."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("recentList")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("recentContent")
        self._rows = QVBoxLayout()
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(0)
        self._rows.addStretch()
        content.setLayout(self._rows)
        self.setWidget(content)
        self._uploads = []

    def count(self):
        return len(self._uploads)

    def clear(self):
        self.set_uploads([])

    def set_uploads(self, uploads):
        uploads = list(uploads)
        # The 5s poll returns the same rows most of the time; rebuilding them
        # resets scroll position and button feedback like "Copied ✓".
        if uploads == self._uploads:
            return
        self._uploads = uploads
        scroll = self.verticalScrollBar().value()
        while self._rows.count() > 1:
            self._rows.takeAt(0).widget().deleteLater()
        for index, upload in enumerate(uploads):
            self._rows.insertWidget(index, RecentUploadRow(upload))
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(scroll))


class RecentUploadRow(QFrame):
    def __init__(self, upload, parent=None):
        super().__init__(parent)
        self.setObjectName("recentRow")

        name = _label(upload.filename, "strong")
        name.setTextFormat(Qt.TextFormat.PlainText)
        name.setWordWrap(True)

        status = _label(upload.status_label)
        status.setTextFormat(Qt.TextFormat.PlainText)
        status.setProperty("chip", upload.status_label.lower())

        title_row = QHBoxLayout()
        title_row.addWidget(name, 1)
        if upload.failed_layers_tooltip:
            warning = _label("⚠", "warning")
            warning.setAccessibleName("Some layers failed")
            warning.setToolTip(upload.failed_layers_tooltip)
            title_row.addWidget(warning, 0, Qt.AlignmentFlag.AlignTop)
        title_row.addWidget(status, 0, Qt.AlignmentFlag.AlignTop)

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        layout.addLayout(title_row)

        if upload.error_reason:
            reason = _label(upload.error_reason, "error")
            reason.setTextFormat(Qt.TextFormat.PlainText)
            reason.setWordWrap(True)
            layout.addWidget(reason)

        if upload.health_warning_label:
            health = _label(upload.health_warning_label, "warning")
            health.setTextFormat(Qt.TextFormat.PlainText)
            health.setToolTip("View health warning details on the web")
            layout.addWidget(health)

        actions = QHBoxLayout()
        if upload.copy_share_url:
            copy_button = QToolButton()
            copy_button.setProperty("variant", "soft")
            copy_button.setIcon(_theme_icon("mActionEditCopy.svg"))
            copy_button.setText("Copy link")
            copy_button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )
            copy_button.setIconSize(QSize(14, 14))
            copy_button.setFixedHeight(ROW_BUTTON_HEIGHT)
            # ponytail: no revert timer; "Copied ✓" stays until this row's data
            # changes (RecentUploadsList skips rebuilding unchanged rows).
            copy_button.clicked.connect(
                lambda: (
                    QApplication.clipboard().setText(upload.copy_share_url),
                    copy_button.setText("Copied ✓"),
                )
            )
            actions.addWidget(copy_button)
        if upload.details_url:
            open_button = QToolButton()
            open_button.setProperty("variant", "soft")
            open_button.setText(f"{upload.details_label} ↗")
            open_button.setFixedHeight(ROW_BUTTON_HEIGHT)
            open_button.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(upload.details_url))
            )
            actions.addWidget(open_button)
        if actions.count():
            actions.addStretch()
            layout.addLayout(actions)
        self.setLayout(layout)


class GeoDelDockWidget(QDockWidget):
    def __init__(
        self,
        refresh_organizations,
        save_and_connect,
        manage_connection,
        return_to_main,
        parent=None,
    ):
        super().__init__(PRODUCT_NAME, parent)

        # Setup / connection management screen
        self.cancel_replacement_button = QPushButton("← Back to uploads")
        self.cancel_replacement_button.setProperty("variant", "link")
        self.cancel_replacement_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_replacement_button.clicked.connect(return_to_main)

        self.setup_title = _label(f"{PRODUCT_NAME} isn’t connected", "title")
        self.setup_explanation = _label(
            f"Connect your {PRODUCT_NAME} account with a Personal API Key to "
            "upload layers from QGIS.",
            "muted",
        )
        self.setup_explanation.setWordWrap(True)
        self.open_setup_button = QPushButton("Get a Personal API Key ↗")
        self.open_setup_button.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl(f"{WEB_URL}/qgis/setup")
            )
        )
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Paste Personal API Key")
        self.api_key.setAccessibleName(f"{PRODUCT_NAME} Personal API Key")
        reveal_key = self.api_key.addAction(
            _theme_icon("mActionShowAllLayers.svg"),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        reveal_key.setToolTip("Show or hide key")
        reveal_key.setCheckable(True)
        # Never carry a previous "show" choice over to the next pasted key.
        self.api_key.textChanged.connect(
            lambda value: value or reveal_key.setChecked(False)
        )
        reveal_key.toggled.connect(
            lambda shown: self.api_key.setEchoMode(
                QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
            )
        )
        self.connect_button = QPushButton("Save and connect")
        self.connect_button.setProperty("variant", "primary")
        self.connect_button.setEnabled(False)
        self.api_key.textChanged.connect(
            lambda value: self.connect_button.setEnabled(bool(value.strip()))
        )
        self.api_key.returnPressed.connect(
            lambda: self.connect_button.isEnabled() and save_and_connect()
        )
        self.connect_button.clicked.connect(save_and_connect)
        self.setup_status = QLabel()
        self.setup_status.setAccessibleName("QGIS Plugin Connection status")
        self.setup_status.setWordWrap(True)
        self.organization_setup_button = QPushButton("Set up a Workspace ↗")
        self.organization_setup_button.setProperty("variant", "primary")
        self.organization_setup_button.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl(f"{WEB_URL}/qgis/setup")
            )
        )
        self.retry_connection_button = QPushButton("Check again")
        self.retry_connection_button.clicked.connect(refresh_organizations)

        self.api_key_label = _label("Personal API Key", "section")
        self.api_key_label.setBuddy(self.api_key)
        retry_row = QHBoxLayout()
        retry_row.addWidget(self.retry_connection_button)
        retry_row.addStretch()
        setup_layout = QVBoxLayout()
        setup_layout.setContentsMargins(14, 12, 14, 12)
        setup_layout.setSpacing(8)
        setup_layout.addLayout(_brand_row())
        setup_layout.addWidget(self.cancel_replacement_button)
        setup_layout.addSpacing(4)
        setup_layout.addWidget(self.setup_title)
        setup_layout.addWidget(self.setup_explanation)
        setup_layout.addWidget(self.open_setup_button)
        setup_layout.addWidget(self.api_key_label)
        setup_layout.addWidget(self.api_key)
        setup_layout.addWidget(self.connect_button)
        setup_layout.addWidget(self.organization_setup_button)
        setup_layout.addWidget(self.setup_status)
        setup_layout.addLayout(retry_row)
        setup_layout.addStretch()
        self.setup_panel = QWidget()
        self.setup_panel.setLayout(setup_layout)

        # Main screen
        self.connected_status = _label("● Connected")
        self.connected_status.setProperty("chip", "ready")
        self.replace_button = _icon_button(
            "mActionOptions.svg", "Connection management"
        )
        self.replace_button.clicked.connect(manage_connection)
        header = _brand_row()
        header.addWidget(self.connected_status)
        header.addWidget(self.replace_button)
        self.connected_panel = QWidget()
        self.connected_panel.setLayout(header)

        self.update_notice = _label(
            f"Please update the {PRODUCT_NAME} plugin to continue."
        )
        self.update_notice.setObjectName("banner")
        self.update_notice.setWordWrap(True)
        self.update_notice.hide()

        self.organizations = QComboBox()
        self.organizations.setAccessibleName(f"{PRODUCT_NAME} workspace")
        self.refresh_button = _icon_button("mActionRefresh.svg", "Refresh workspaces")
        self.refresh_button.clicked.connect(refresh_organizations)
        picker_row = QHBoxLayout()
        picker_row.addWidget(self.organizations, 1)
        picker_row.addWidget(self.refresh_button)

        self.folders = QComboBox()
        self.folders.setAccessibleName(f"{PRODUCT_NAME} folder")
        self.folders.addItem("Files (root)", "")

        self.layers = QListWidget()
        self.layers.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.layers.setAccessibleName(f"{PRODUCT_NAME} project layers")
        self.layers.setMinimumHeight(120)
        self.layers_empty = _label(
            "No vector layers in this project.\nAdd one, or upload a file instead.",
            "empty",
        )
        self.layers_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layers_empty.setWordWrap(True)
        self.layers_empty.hide()
        self.layers_hint = _label("", "muted")
        self.layers.model().rowsInserted.connect(self._layers_count_changed)
        self.layers.model().rowsRemoved.connect(self._layers_count_changed)
        self.layers.model().modelReset.connect(self._layers_count_changed)
        # Selection model, not the view: _refresh_layers blocks the view's signals.
        self.layers.selectionModel().selectionChanged.connect(
            self._layer_selection_changed
        )
        self._layer_selection_changed()

        self.browse_button = FileDropZone()
        self.file_path = self.browse_button.file_path
        self.source_layers_button = QToolButton()
        self.source_layers_button.setText("Layers")
        self.source_layers_button.setProperty("segment", "left")
        self.source_file_button = QToolButton()
        self.source_file_button.setText("File")
        self.source_file_button.setProperty("segment", "right")
        source_group = QButtonGroup(self)
        for button in (self.source_layers_button, self.source_file_button):
            button.setCheckable(True)
            source_group.addButton(button)
        self.source_layers_button.setChecked(True)
        source_row = QHBoxLayout()
        source_row.setSpacing(0)
        source_row.addWidget(_label("WHAT TO UPLOAD", "section"))
        source_row.addStretch()
        source_row.addWidget(self.source_layers_button)
        source_row.addWidget(self.source_file_button)

        layers_layout = QVBoxLayout()
        layers_layout.setContentsMargins(0, 0, 0, 0)
        layers_layout.addWidget(self.layers)
        layers_layout.addWidget(self.layers_empty)
        layers_layout.addWidget(self.layers_hint)
        layers_page = QWidget()
        layers_page.setLayout(layers_layout)
        file_layout = QVBoxLayout()
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.addWidget(self.browse_button)
        file_layout.addStretch()
        file_page = QWidget()
        file_page.setLayout(file_layout)
        self.source_pages = QStackedWidget()
        self.source_pages.addWidget(layers_page)
        self.source_pages.addWidget(file_page)

        self.upload_name = QLineEdit()
        self.upload_name.setPlaceholderText(f"Name shown in {PRODUCT_NAME}")
        self.upload_name.setAccessibleName(f"{PRODUCT_NAME} upload name")
        self.upload_button = QPushButton(f"Upload to {PRODUCT_NAME}")
        self.upload_button.setProperty("variant", "primary")
        self.upload_button.setEnabled(False)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.hide()
        self.status = _label("", "muted")
        self.status.setWordWrap(True)

        self.recent_uploads = RecentUploadsList()
        self.recent_uploads.setAccessibleName(f"Recent {PRODUCT_NAME} uploads")
        self.recent_uploads.setMinimumHeight(260)
        self.recent_count = _label("", "muted")
        self.recent_status = _label(
            "Choose a workspace to load recent uploads.", "muted"
        )
        self.recent_status.setWordWrap(True)
        recent_row = QHBoxLayout()
        recent_row.addWidget(_label("RECENT UPLOADS", "section"))
        recent_row.addStretch()
        recent_row.addWidget(self.recent_count)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(6)
        main_layout.addWidget(self.connected_panel)
        main_layout.addWidget(self.update_notice)
        main_layout.addWidget(_label("DESTINATION", "section"))
        main_layout.addLayout(picker_row)
        main_layout.addWidget(self.folders)
        main_layout.addLayout(source_row)
        main_layout.addWidget(self.source_pages)
        main_layout.addWidget(_label("NAME", "section"))
        main_layout.addWidget(self.upload_name)
        main_layout.addSpacing(4)
        main_layout.addWidget(self.upload_button)
        main_layout.addWidget(self.progress)
        main_layout.addWidget(self.status)
        main_layout.addLayout(recent_row)
        main_layout.addWidget(self.recent_uploads, 1)
        main_layout.addWidget(self.recent_status)
        main_content = QWidget()
        main_content.setLayout(main_layout)
        self.main_panel = QScrollArea()
        self.main_panel.setWidgetResizable(True)
        self.main_panel.setWidget(main_content)

        self.screens = QStackedWidget()
        self.screens.setStyleSheet(DOCK_STYLE)
        self.screens.addWidget(self.setup_panel)
        self.screens.addWidget(self.main_panel)
        self.setWidget(self.screens)

    def show_setup(self, message="", allow_cancel=False):
        self.setup_title.setText(
            "Connection management"
            if allow_cancel
            else f"{PRODUCT_NAME} isn’t connected"
        )
        self.setup_explanation.setText(
            "Your key is stored encrypted in the QGIS Authentication Manager. "
            "Paste a new key to replace it."
            if allow_cancel
            else f"Connect your {PRODUCT_NAME} account with a Personal API Key to "
            "upload layers from QGIS."
        )
        self.setup_explanation.setVisible(True)
        self.screens.setCurrentWidget(self.setup_panel)
        self.open_setup_button.show()
        self.api_key_label.show()
        self.api_key.show()
        self.api_key.setEnabled(True)
        self.connect_button.show()
        self.connect_button.setText(
            "Replace API key" if allow_cancel else "Save and connect"
        )
        self.connect_button.setEnabled(bool(self.api_key.text().strip()))
        self.organization_setup_button.hide()
        self.retry_connection_button.setVisible(allow_cancel)
        self.retry_connection_button.setEnabled(True)
        self.cancel_replacement_button.setVisible(allow_cancel)
        self.setup_status.setText(message)

    def show_connecting(
        self, message="Checking this Personal API Key…", allow_cancel=False
    ):
        self.show_setup(message, allow_cancel)
        self.api_key.setEnabled(False)
        self.connect_button.setEnabled(False)
        self.retry_connection_button.setEnabled(False)

    def show_organization_setup(self):
        self.show_setup()
        self.setup_title.setText("Workspace setup required")
        self.setup_explanation.setText(
            f"{PRODUCT_NAME} accepted this Personal API Key, but no Workspace is "
            "available. Complete Workspace setup on the web, then retry."
        )
        self.open_setup_button.hide()
        self.api_key_label.hide()
        self.api_key.hide()
        self.connect_button.hide()
        self.organization_setup_button.show()
        self.retry_connection_button.show()

    def show_connected(self):
        self.setup_status.clear()
        self.screens.setCurrentWidget(self.main_panel)
        self.api_key.setEnabled(True)
        self.api_key.clear()

    def show_source(self, use_file):
        button = self.source_file_button if use_file else self.source_layers_button
        button.setChecked(True)
        self.source_pages.setCurrentIndex(1 if use_file else 0)

    def _layers_count_changed(self, *_args):
        empty = self.layers.count() == 0
        self.layers.setVisible(not empty)
        self.layers_hint.setVisible(not empty)
        self.layers_empty.setVisible(empty)

    def _layer_selection_changed(self, *_args):
        count = len(self.layers.selectedItems())
        self.layers_hint.setText(
            f"{count} layer{'s' if count != 1 else ''} selected"
            if count
            else "Select layers · Ctrl/⌘-click to pick several"
        )

    def set_organizations(self, organizations, selected_id=""):
        signals_were_blocked = self.organizations.blockSignals(True)
        try:
            self.organizations.clear()
            for organization in organizations:
                self.organizations.addItem(organization["name"], organization["id"])
            selected_index = self.organizations.findData(selected_id)
            if selected_index >= 0:
                self.organizations.setCurrentIndex(selected_index)
        finally:
            self.organizations.blockSignals(signals_were_blocked)
        self.status.setText("" if organizations else "No workspaces available.")

    def set_folders(self, folders, selected_id=""):
        self.folders.clear()
        self.folders.addItem("Files (root)", "")
        for folder in folders:
            self.folders.addItem(folder["name"], folder["id"])
        selected_index = self.folders.findData(selected_id)
        self.folders.setCurrentIndex(max(selected_index, 0))

    def set_uploading(self, uploading):
        for control in (
            self.organizations,
            self.folders,
            self.refresh_button,
            self.source_layers_button,
            self.source_file_button,
            self.layers,
            self.browse_button,
            self.upload_name,
            self.upload_button,
        ):
            control.setEnabled(not uploading)
        self.upload_button.setText(
            "Uploading…" if uploading else f"Upload to {PRODUCT_NAME}"
        )
        self.progress.setValue(0)
        self.progress.setVisible(uploading)
        if uploading:
            self.status.clear()

    def set_recent_uploads(self, uploads):
        self.recent_uploads.set_uploads(uploads)
        self.recent_count.setText(str(len(uploads)) if uploads else "")
        self.recent_status.setText(
            "" if uploads else "No uploads yet. They’ll show up here."
        )

    def set_loading(self, loading):
        self.refresh_button.setEnabled(not loading)
        self.retry_connection_button.setEnabled(not loading)
        self.organizations.setEnabled(not loading)
        if loading:
            self.status.setText("Loading workspaces…")


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
        self._uploads_task = None
        self._version_task = None
        self._recent_timer = None
        self._selected_path = None
        self._candidate_api_key = None
        self._connection_valid = False
        self._connection_version = 0

    def initGui(self):  # noqa: N802 - QGIS plugin API
        icon = QIcon(str(Path(__file__).with_name("icon.svg")))
        self.action = QAction(icon, PRODUCT_NAME, self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.setToolTip(f"Open {PRODUCT_NAME}")
        self.action.triggered.connect(self._toggle_panel)
        self.iface.addToolBarIcon(self.action)

        self.dock = GeoDelDockWidget(
            self._refresh_organizations,
            self._save_and_connect,
            self._manage_connection,
            self._return_to_main,
            self.iface.mainWindow(),
        )
        self.dock.show_setup()
        self.dock.organizations.currentIndexChanged.connect(self._organization_changed)
        self.dock.folders.currentIndexChanged.connect(self._folder_changed)
        self.dock.layers.itemSelectionChanged.connect(self._layers_changed)
        self.dock.browse_button.clicked.connect(self._browse_file)
        self.dock.browse_button.file_dropped.connect(self._choose_file)
        self.dock.source_layers_button.clicked.connect(
            lambda: self._source_changed(False)
        )
        self.dock.source_file_button.clicked.connect(
            lambda: self._source_changed(True)
        )
        self.dock.upload_name.textChanged.connect(self._update_upload_enabled)
        self.dock.upload_button.clicked.connect(self._start_upload)
        self.dock.visibilityChanged.connect(self._panel_visibility_changed)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.dock.hide()
        self._recent_timer = QTimer(self.dock)
        self._recent_timer.setInterval(RECENT_REFRESH_MILLISECONDS)
        self._recent_timer.timeout.connect(self._refresh_recent_uploads)
        self._organization_timer = QTimer(self.dock)
        self._organization_timer.setSingleShot(True)
        self._organization_timer.setInterval(CONNECTION_TIMEOUT_MILLISECONDS)
        self._organization_timer.timeout.connect(self._organization_timed_out)
        project = QgsProject.instance()
        project.layersAdded.connect(self._refresh_layers)
        project.layersRemoved.connect(self._refresh_layers)
        project.cleared.connect(self._refresh_layers)
        self._refresh_layers()
        self._check_version()

    def unload(self):
        project = QgsProject.instance()
        disconnect_signal(project.layersAdded, self._refresh_layers)
        disconnect_signal(project.layersRemoved, self._refresh_layers)
        disconnect_signal(project.cleared, self._refresh_layers)
        for task in (
            self._organization_task,
            self._folder_task,
            self._upload_task,
            self._uploads_task,
            self._version_task,
        ):
            cancel_task(task)
        self._organization_task = None
        self._folder_task = None
        self._upload_task = None
        self._uploads_task = None
        self._version_task = None
        if self._recent_timer:
            self._recent_timer.stop()
            self._recent_timer = None
        if self._organization_timer:
            self._organization_timer.stop()
            self._organization_timer = None
        if self.action:
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

    def _toggle_panel(self, visible):
        self.dock.setVisible(visible)

    def _panel_visibility_changed(self, visible):
        if self.action:
            self.action.setChecked(visible)
        if visible:
            self._refresh_layers()
            self._refresh_organizations()
            if self._recent_timer:
                self._recent_timer.start()
        else:
            if self._recent_timer:
                self._recent_timer.stop()
            cancel_task(self._uploads_task)
            self._uploads_task = None

    def _check_version(self):
        cancel_task(self._version_task)
        task = QgsTask.fromFunction(
            f"Check {PRODUCT_NAME} plugin version",
            _requires_update,
            on_finished=lambda error, result=None: self._version_checked(
                task, error, result
            ),
            server_url=API_URL,
        )
        self._version_task = task
        QgsApplication.taskManager().addTask(task)

    def _version_checked(self, task, error, requires_update):
        if task is not self._version_task:
            return
        self._version_task = None
        if self.dock is None or error is not None or requires_update is None:
            return
        self.dock.update_notice.setVisible(requires_update)
        if requires_update:
            self.iface.messageBar().pushWarning(
                PRODUCT_NAME,
                f"Please update the {PRODUCT_NAME} plugin to continue.",
            )

    def _refresh_organizations(self):
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
        task = QgsTask.fromFunction(
            f"Load {PRODUCT_NAME} workspaces",
            _load_organizations,
            on_finished=lambda error, result=None: self._organizations_loaded(
                task, version, error, result
            ),
            server_url=API_URL,
            api_key=api_key,
        )
        self._organization_task = task
        self._organization_version = version
        if self._organization_timer:
            self._organization_timer.start()
        QgsApplication.taskManager().addTask(task)

    def _organization_timed_out(self):
        # requests' timeout doesn't bound DNS or a task that never runs.
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
        api_key = self.dock.api_key.text().strip()
        if not api_key:
            self.dock.setup_status.setText("Paste a Personal API Key.")
            return
        cancel_task(self._organization_task)
        self._candidate_api_key = api_key
        self.dock.show_connecting(allow_cancel=self._connection_valid)
        self._start_organization_request(api_key)

    def _manage_connection(self):
        cancel_task(self._organization_task)
        self._organization_task = None
        self.dock.set_loading(False)
        self.dock.show_setup(allow_cancel=True)

    def _return_to_main(self):
        cancel_task(self._organization_task)
        self._organization_task = None
        self._candidate_api_key = None
        self.dock.set_loading(False)
        self.dock.show_connected()

    def _connection_rejected(self, version):
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
        task = QgsTask.fromFunction(
            f"Load recent {PRODUCT_NAME} uploads",
            _load_recent_uploads,
            on_finished=lambda error, result=None: self._recent_uploads_loaded(
                task, version, organization_id, error, result
            ),
            server_url=server_url,
            api_key=api_key,
            organization_id=organization_id,
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
        task = QgsTask.fromFunction(
            f"Load {PRODUCT_NAME} folders",
            _load_folders,
            on_finished=lambda error, result=None: self._folders_loaded(
                task, version, organization_id, error, result
            ),
            server_url=API_URL,
            api_key=api_key,
            organization_id=organization_id,
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
        start = self.settings.value(f"{SETTINGS_PREFIX}/lastDirectory", "", type=str)
        filename, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            "Choose a file to share",
            start,
            "Supported files (*.zip *.geojson *.json)",
        )
        if filename:
            self._choose_file(filename)

    def _choose_file(self, filename):
        path = Path(filename)
        if path.suffix.lower() not in (".zip", ".geojson", ".json"):
            self.iface.messageBar().pushCritical(
                PRODUCT_NAME, "Choose a .zip, .geojson, or .json file."
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
            and bool(self.dock.organizations.currentData())
            and bool(self.dock.upload_name.text().strip())
        )

    def _upload_filename(self, suffix):
        name = self.dock.upload_name.text().strip()
        if not name or "/" in name or "\\" in name:
            self.iface.messageBar().pushCritical(
                PRODUCT_NAME, "Upload name cannot be empty or contain slashes."
            )
            return None
        filename = name if name.lower().endswith(suffix) else f"{name}{suffix}"
        if len(filename) > 255:
            self.iface.messageBar().pushCritical(
                PRODUCT_NAME, "Upload name must be 255 characters or fewer."
            )
            return None
        return filename

    def _upload_destination(self):
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
        }

    def _new_upload_task(
        self,
        path,
        upload_filename,
        destination,
        version,
        artifact=None,
    ):
        task = QgsTask.fromFunction(
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

    def _run_upload_task(self, task, exporting=False):
        self._upload_task = task
        self.dock.set_uploading(True)
        if exporting:
            self.dock.upload_button.setText("Preparing layers…")

        def show_progress(value):
            # Queued signal: may arrive after unload() or after a newer task started.
            if self.dock is not None and task is self._upload_task:
                self.dock.progress.setValue(int(value))

        task.progressChanged.connect(show_progress)
        QgsApplication.taskManager().addTask(task)

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
        if file_size > MAX_FILE_SIZE:
            self.iface.messageBar().pushCritical(
                PRODUCT_NAME, f"File exceeds the {MAX_FILE_SIZE_LABEL} upload limit."
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
            export = LayerExport(layers)
        except GeoDelError as error:
            self.iface.messageBar().pushCritical(PRODUCT_NAME, str(error))
            return
        upload_filename = self._upload_filename(export.suffix)
        if upload_filename is None:
            return
        destination = self._upload_destination()
        if destination is None:
            return

        version = self._connection_version
        task = export.create_task(
            lambda error, artifact: self._layer_export_finished(
                task, version, upload_filename, destination, error, artifact
            )
        )
        self._run_upload_task(task, exporting=True)

    def _layer_export_finished(
        self, task, version, upload_filename, destination, error, artifact
    ):
        if task is not self._upload_task:
            if artifact:
                artifact.cleanup()
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
        self._run_upload_task(
            self._new_upload_task(
                None, upload_filename, destination, version, artifact=artifact
            )
        )

    def _upload_finished(self, task, version, server_url, error, result):
        if task is not self._upload_task:
            return
        self._upload_task = None
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
