"""GeoDel dock widgets and styling, independent of plugin lifecycle."""
from pathlib import Path

from qgis.PyQt.QtCore import QSize, QTimer, QUrl, Qt, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QComboBox, QDockWidget,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QProgressBar,
    QPushButton, QScrollArea, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)
from qgis.core import QgsApplication

from .client import MAX_FILE_SIZE_LABEL
from .config import PRODUCT_NAME, WEB_URL

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
        self._scroll_position = 0
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._restore_scroll)

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
        self._scroll_position = self.verticalScrollBar().value()
        while self._rows.count() > 1:
            self._rows.takeAt(0).widget().deleteLater()
        for index, upload in enumerate(uploads):
            self._rows.insertWidget(index, RecentUploadRow(upload))
        self._scroll_timer.start(0)

    def _restore_scroll(self):
        self.verticalScrollBar().setValue(self._scroll_position)


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
    refresh_requested = pyqtSignal()
    connect_requested = pyqtSignal()
    manage_requested = pyqtSignal()
    return_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(PRODUCT_NAME, parent)
        self.setObjectName("GeoDelDockWidget")

        # Setup / connection management screen
        self.cancel_replacement_button = QPushButton("← Back to uploads")
        self.cancel_replacement_button.setProperty("variant", "link")
        self.cancel_replacement_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_replacement_button.clicked.connect(self.return_requested)

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
            lambda: self.connect_button.isEnabled() and self.connect_requested.emit()
        )
        self.connect_button.clicked.connect(self.connect_requested)
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
        self.retry_connection_button.clicked.connect(self.refresh_requested)

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
        self.replace_button.clicked.connect(self.manage_requested)
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
        self.refresh_button.clicked.connect(self.refresh_requested)
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

        self.cancel_upload_button = QPushButton("Cancel upload")
        self.cancel_upload_button.setAccessibleName("Cancel upload")
        self.cancel_upload_button.setVisible(False)

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
        upload_actions = QHBoxLayout()
        upload_actions.addWidget(self.upload_button, 1)
        upload_actions.addWidget(self.cancel_upload_button)
        main_layout.addLayout(upload_actions)
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
        self.cancel_upload_button.setVisible(uploading)
        self.cancel_upload_button.setEnabled(uploading)
        self.cancel_upload_button.setText("Cancel upload")
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
