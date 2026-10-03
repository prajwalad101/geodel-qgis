import ast
from configparser import ConfigParser
from pathlib import Path
from xml.etree import ElementTree


PLUGIN_PATH = Path(__file__).parents[1] / "geodel/plugin.py"


def _toolbar_icon_expression():
    tree = ast.parse(
        PLUGIN_PATH.read_text()
    )
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "QIcon"
        ):
            return ast.Expression(node.args[0])
    raise AssertionError("toolbar QIcon call not found")


def test_toolbar_and_metadata_use_packaged_icon():
    expression = compile(_toolbar_icon_expression(), "plugin.py", "eval")
    icon_path = Path(eval(expression, {"Path": Path, "__file__": str(PLUGIN_PATH)}))
    metadata = ConfigParser()
    metadata.read(PLUGIN_PATH.with_name("metadata.txt"))
    assert icon_path == PLUGIN_PATH.with_name(metadata["general"]["icon"])
    assert icon_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert ElementTree.parse(icon_path.with_suffix(".svg")).getroot().tag == "{http://www.w3.org/2000/svg}svg"


def _plugin_method(class_name, method_name, globals_=None):
    source = PLUGIN_PATH.with_name("dock.py") if class_name == "GeoDelDockWidget" else PLUGIN_PATH
    tree = ast.parse(source.read_text())
    owner = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node
        for node in owner.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )
    namespace = dict(globals_ or {})
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(
                body=[
                    ast.ClassDef(
                        name="Subject",
                        bases=[],
                        keywords=[],
                        body=[method],
                        decorator_list=[],
                    )
                ],
                type_ignores=[],
            )),
            "plugin.py",
            "exec",
        ),
        namespace,
    )
    return getattr(namespace["Subject"], method_name)


def test_organization_population_does_not_emit_user_selection():
    class Combo:
        def __init__(self):
            self.blocked = False
            self.items = []
            self.changes = 0

        def blockSignals(self, blocked):
            previous = self.blocked
            self.blocked = blocked
            return previous

        def clear(self):
            self.items.clear()
            if not self.blocked:
                self.changes += 1

        def addItem(self, name, id_):
            self.items.append((name, id_))
            if not self.blocked:
                self.changes += 1

        def findData(self, id_):
            return next(
                (index for index, item in enumerate(self.items) if item[1] == id_),
                -1,
            )

        def setCurrentIndex(self, _index):
            if not self.blocked:
                self.changes += 1

    class Status:
        def setText(self, _text):
            pass

    subject = type("Dock", (), {"organizations": Combo(), "status": Status()})()
    set_organizations = _plugin_method("GeoDelDockWidget", "set_organizations")

    set_organizations(
        subject,
        [{"id": "org-1", "name": "Field Team"}],
        "org-1",
    )

    assert subject.organizations.changes == 0
    assert subject.organizations.blocked is False


def test_connection_request_starts_after_connecting():
    calls = []

    class Text:
        def text(self):
            return " geodel_key "

    class Dock:
        api_key = Text()

        def show_connecting(self, allow_cancel=False):
            calls.append(("connecting", allow_cancel))

    subject = type(
        "Plugin",
        (),
        {
            "dock": Dock(),
            "_organization_task": None,
            "_connection_valid": True,
            "_start_organization_request": lambda _self, key: calls.append(
                ("request", key)
            ),
        },
    )()
    save_and_connect = _plugin_method(
        "GeoDelPlugin",
        "_save_and_connect",
        {"cancel_task": lambda _task: None},
    )

    save_and_connect(subject)

    assert calls == [
        ("connecting", True),
        ("request", "geodel_key"),
    ]


def test_connection_management_is_separate_from_uploads():
    class Widget:
        def __init__(self, text="", visible=True):
            self.value = text
            self.visible = visible
            self.enabled = True

        def hide(self):
            self.visible = False

        def show(self):
            self.visible = True

        def setVisible(self, visible):
            self.visible = visible

        def setText(self, text):
            self.value = text

        def text(self):
            return self.value

        def setEnabled(self, enabled):
            self.enabled = enabled

        def clear(self):
            self.value = ""

    class Screens:
        current = None

        def setCurrentWidget(self, widget):
            self.current = widget

        def currentWidget(self):
            return self.current

    subject = type(
        "Dock",
        (),
        {
            name: Widget()
            for name in (
                "setup_title",
                "setup_explanation",
                "setup_panel",
                "main_panel",
                "open_setup_button",
                "api_key_label",
                "api_key",
                "connect_button",
                "organization_setup_button",
                "retry_connection_button",
                "cancel_replacement_button",
                "setup_status",
            )
        },
    )()
    subject.screens = Screens()
    subject.api_key.value = "replacement-key"

    show_setup = _plugin_method(
        "GeoDelDockWidget", "show_setup", {"PRODUCT_NAME": "Maply"}
    )
    show_setup(subject, "Paste a replacement key.", allow_cancel=True)

    assert subject.setup_title.value == "Connection management"
    assert subject.screens.currentWidget() is subject.setup_panel
    assert subject.cancel_replacement_button.visible
    assert subject.retry_connection_button.visible
    assert subject.connect_button.value == "Replace API key"

    subject.show_setup = lambda message, allow_cancel=False: show_setup(
        subject, message, allow_cancel
    )
    show_connecting = _plugin_method(
        "GeoDelDockWidget", "show_connecting", {"PRODUCT_NAME": "Maply"}
    )
    show_connecting(subject, allow_cancel=True)

    assert subject.screens.currentWidget() is subject.setup_panel
    assert subject.cancel_replacement_button.visible
    assert not subject.api_key.enabled
    assert not subject.retry_connection_button.enabled

    show_connected = _plugin_method("GeoDelDockWidget", "show_connected")
    show_connected(subject)
    assert subject.screens.currentWidget() is subject.main_panel

    show_setup(subject)
    assert subject.screens.currentWidget() is subject.setup_panel
    assert not subject.cancel_replacement_button.visible
    assert not subject.retry_connection_button.visible


def test_delayed_auth_failure_does_not_remove_replacement_key():
    class AuthenticationError(Exception):
        pass

    class Settings:
        auth_config_id = "replacement-config"

        def value(self, _name, _default, type):
            return self.auth_config_id

        def remove(self, _name):
            self.auth_config_id = ""

    class Organizations:
        def currentData(self):
            return "org-1"

        def clear(self):
            pass

    class Dock:
        organizations = Organizations()

        def show_setup(self, _message):
            pass

    class AuthManager:
        removed = []

        def removeAuthenticationConfig(self, config_id):
            self.removed.append(config_id)

    manager = AuthManager()
    qgs_application = type("QgsApplication", (), {"authManager": lambda: manager})
    globals_ = {
        "AuthenticationError": AuthenticationError,
        "QgsApplication": qgs_application,
        "SETTINGS_PREFIX": "GeoDel",
        "SAVED_KEY_REJECTED_MESSAGE": "rejected",
    }
    rejected = _plugin_method("GeoDelPlugin", "_connection_rejected", globals_)
    loaded = _plugin_method("GeoDelPlugin", "_recent_uploads_loaded", globals_)
    settings = Settings()
    subject = type(
        "Plugin",
        (),
        {
            "_connection_version": 1,
            "_connection_valid": True,
            "_candidate_api_key": None,
            "settings": settings,
            "dock": Dock(),
            "_connection_rejected": lambda self, version: rejected(self, version),
        },
    )()

    old_task = object()
    subject._uploads_task = old_task
    loaded(subject, old_task, 0, "org-1", AuthenticationError(), None)
    assert settings.auth_config_id == "replacement-config"
    assert subject._connection_valid
    assert manager.removed == []

    current_task = object()
    subject._uploads_task = current_task
    loaded(subject, current_task, 1, "org-1", AuthenticationError(), None)
    assert settings.auth_config_id == ""
    assert not subject._connection_valid
    assert manager.removed == ["replacement-config"]


def test_layer_export_keeps_original_connection_version():
    versions = []
    task = object()

    class Plugin:
        _upload_task = task

        def _new_upload_task(self, _path, _name, _destination, version, **_kwargs):
            versions.append(version)

        def _run_upload_task(self, _task):
            pass

    subject = Plugin()
    export_finished = _plugin_method("GeoDelPlugin", "_layer_export_finished")

    export_finished(subject, task, 0, "roads.geojson", {}, None, object())

    assert versions == [0]


def test_folder_selector_uses_top_level_names_and_restores_selection():
    class Combo:
        def clear(self):
            self.items = []

        def addItem(self, name, id_):
            self.items.append((name, id_))

        def findData(self, id_):
            return next((i for i, item in enumerate(self.items) if item[1] == id_), -1)

        def setCurrentIndex(self, index):
            self.index = index

    subject = type("Dock", (), {"folders": Combo()})()
    set_folders = _plugin_method("GeoDelDockWidget", "set_folders")
    folders = [{"id": "projects", "name": "Projects"},
               {"id": "maps", "name": "Maps"}]
    set_folders(subject, folders, "maps")
    assert subject.folders.items == [("Files (root)", ""), ("Projects", "projects"), ("Maps", "maps")]
    assert subject.folders.index == 2
    set_folders(subject, folders, "deleted-folder")
    assert subject.folders.index == 0
