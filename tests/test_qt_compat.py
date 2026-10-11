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
