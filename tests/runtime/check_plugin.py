"""Integration tests using real QGIS, Qt widgets, tasks and authentication.

Only the QgisInterface host and service responses are adapted. No Qt/QGIS
classes are stubbed. Run with scripts/test-qgis.py in QGIS's Python environment.
"""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.environ.get(
    "GEODEL_PACKAGE_ROOT", str(Path(__file__).resolve().parents[2]),
))

from qgis.PyQt.QtCore import QCoreApplication, QEvent, QT_VERSION_STR, QTimer
from qgis.PyQt.QtWidgets import (
    QApplication, QDockWidget, QMainWindow, QMenu, QToolBar, QToolButton,
)
from qgis.core import (
    Qgis, QgsApplication, QgsAuthMethodConfig, QgsProject, QgsSettings,
)
from qgis.gui import QgsMessageBar


class Interface:
    """Public host interface backed by real Qt menus, toolbar and dock host."""

    def __init__(self):
        self.window = QMainWindow()
        self.menu = QMenu("Web", self.window)
        self.toolbar = QToolBar("Web", self.window)
        self.window.addToolBar(self.toolbar)
        self.bar = QgsMessageBar(self.window)
        self.window.show()

    def mainWindow(self):
        return self.window

    def webMenu(self):
        return self.menu

    def addPluginToWebMenu(self, name, action):
        self.menu.addAction(action)

    def removePluginWebMenu(self, name, action):
        self.menu.removeAction(action)

    def addWebToolBarIcon(self, action):
        self.toolbar.addAction(action)

    def removeWebToolBarIcon(self, action):
        self.toolbar.removeAction(action)

    def addDockWidget(self, area, dock):
        self.window.addDockWidget(area, dock)

    def removeDockWidget(self, dock):
        self.window.removeDockWidget(dock)

    def messageBar(self):
        return self.bar


def flush_deletes():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    if not predicate():
        raise AssertionError("QGIS operation did not finish within five seconds")
    QApplication.processEvents()


class PluginRuntimeTests(unittest.TestCase):
    def setUp(self):
        from geodel import classFactory
        from geodel.client import GeoDelClient

        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.network = self.patches.enter_context(patch(
            "geodel.qgis_transport.QgisTransport.request",
            side_effect=AssertionError("Network forbidden in runtime tests"),
        ))
        self.version = self.patches.enter_context(patch.object(
            GeoDelClient, "requires_update", return_value=False,
        ))
        self.patches.enter_context(patch.object(
            GeoDelClient, "list_organizations",
            return_value=[{"id": "org-1", "name": "Test Workspace"}],
        ))
        self.patches.enter_context(patch.object(
            GeoDelClient, "list_folders", return_value=[],
        ))
        self.uploads = self.patches.enter_context(patch.object(
            GeoDelClient, "list_recent_uploads", return_value=[],
        ))
        self.iface = Interface()
        self.plugin = classFactory(self.iface)

    def tearDown(self):
        self.plugin.unload()
        wait_until(lambda: QgsApplication.taskManager().countActiveTasks() == 0)
        flush_deletes()
        self.iface.window.close()
        self.iface.window.deleteLater()
        flush_deletes()
        self.network.assert_not_called()
        QgsSettings().remove("GeoDel")

    def connect_key(self, key):
        self.plugin.dock.api_key.setText(key)
        self.plugin.dock.connect_button.click()
        wait_until(lambda: self.plugin.dock.api_key.text() == "")
        self.assertIs(self.plugin.dock.screens.currentWidget(), self.plugin.dock.main_panel)

    def read_stored_key(self, config_id):
        from geodel.auth_compat import unpack_auth_result

        config = QgsAuthMethodConfig()
        loaded, config = unpack_auth_result(
            QgsApplication.authManager().loadAuthenticationConfig(config_id, config, True),
            config,
        )
        self.assertTrue(loaded)
        return config.config("password")

    def test_entry_point_open_close_unload_and_reload(self):
        for _ in range(2):
            self.plugin.initGui()
            self.plugin.initGui()
            action, dock = self.plugin.action, self.plugin.dock
            self.assertEqual(action.objectName(), "GeoDelAction")
            self.assertEqual(dock.objectName(), "GeoDelDockWidget")
            self.assertEqual(self.iface.webMenu().actions(), [action])
            self.assertEqual(self.iface.toolbar.actions(), [action])
            self.assertEqual(
                self.iface.window.findChildren(QDockWidget, "GeoDelDockWidget"), [dock],
            )
            action.trigger()
            QApplication.processEvents()
            self.assertTrue(dock.isVisible())
            dock.close()
            self.assertFalse(action.isChecked())
            action.trigger()
            QApplication.processEvents()
            self.assertTrue(dock.isVisible())
            timers = dock.findChildren(QTimer)
            self.assertTrue(any(timer.isActive() for timer in timers))
            self.plugin.unload()
            self.assertFalse(any(timer.isActive() for timer in timers))
            self.assertEqual(self.iface.webMenu().actions(), [])
            self.assertEqual(self.iface.toolbar.actions(), [])
            # Old senders remain valid before deferred deletion; none may call controller.
            action.trigger()
            dock.connect_requested.emit()
            dock.source_file_button.click()
            QgsProject.instance().clear()
            flush_deletes()
            self.assertEqual(
                self.iface.window.findChildren(QDockWidget, "GeoDelDockWidget"), [],
            )
            self.assertEqual(
                self.iface.window.findChildren(type(action), "GeoDelAction"), [],
            )
            self.plugin.unload()

    def test_authentication_storage_survives_reload_without_plaintext_settings(self):
        manager = QgsApplication.authManager()
        self.assertFalse(manager.isDisabled())
        self.assertTrue(manager.setMasterPassword("synthetic-runtime-master-password", True))
        self.plugin.initGui()
        self.plugin.action.trigger()
        key = "synthetic-personal-api-key"
        self.connect_key(key)
        config_id = QgsSettings().value("GeoDel/authConfigId", "", type=str)
        self.assertTrue(config_id)
        self.assertEqual(self.read_stored_key(config_id), key)
        self.plugin.unload()
        flush_deletes()
        self.plugin.initGui()
        self.plugin.action.trigger()
        wait_until(lambda: self.plugin.dock.screens.currentWidget() is self.plugin.dock.main_panel)
        self.plugin.dock.replace_button.click()
        self.connect_key("synthetic-replacement-key")
        self.assertEqual(QgsSettings().value("GeoDel/authConfigId", "", type=str), config_id)
        self.assertEqual(self.read_stored_key(config_id), "synthetic-replacement-key")
        settings = QgsSettings()
        settings.sync()
        for name in settings.allKeys():
            self.assertNotIn(key, str(settings.value(name)))
            self.assertNotIn("synthetic-replacement-key", str(settings.value(name)))
        # Check the disposable database and settings on disk, not only their API values.
        for path in Path(os.environ["GEODEL_RUNTIME_ROOT"]).rglob("*"):
            if path.is_file():
                self.assertNotIn(key.encode(), path.read_bytes())
                self.assertNotIn(b"synthetic-replacement-key", path.read_bytes())
        self.assertTrue(manager.removeAuthenticationConfig(config_id))

    def test_unload_cancels_active_task_and_ignores_late_completion_after_reload(self):
        started, release = Event(), Event()

        def delayed_version():
            started.set()
            release.wait(5)
            return True

        self.version.side_effect = delayed_version
        self.plugin.initGui()
        wait_until(started.is_set)
        old_task = next(
            task for task in QgsApplication.taskManager().tasks()
            if task.description() == "Check GeoDel plugin version"
        )
        self.plugin.unload()
        self.assertTrue(old_task.isCanceled())
        self.version.side_effect = None
        self.plugin.initGui()
        self.addCleanup(release.set)
        release.set()
        wait_until(lambda: QgsApplication.taskManager().countActiveTasks() == 0)
        self.assertTrue(self.plugin.dock.update_notice.isHidden())
        self.assertEqual(len(self.iface.toolbar.actions()), 1)

    def test_queued_signal_from_old_dock_cannot_connect_reloaded_plugin(self):
        self.plugin.initGui()
        dock = self.plugin.dock
        # Cross-thread emission queues delivery on the GUI thread.
        sender = Thread(target=dock.connect_requested.emit)
        sender.start()
        sender.join()
        self.plugin.unload()
        self.plugin.initGui()
        self.plugin.dock.api_key.setText("synthetic-unsubmitted-key")
        wait_until(lambda: QgsApplication.taskManager().countActiveTasks() == 0)
        self.assertEqual(self.plugin.dock.api_key.text(), "synthetic-unsubmitted-key")
        self.assertTrue(self.plugin.dock.connect_button.isEnabled())

    def test_recent_upload_share_link_and_pending_scroll_are_safe_on_unload(self):
        from geodel.recent_upload import RecentUpload

        self.plugin.initGui()
        upload = RecentUpload(
            "roads.geojson", "Ready", False, None, None, None,
            "https://example.invalid/s/synthetic-token", None, None,
        )
        self.plugin.dock.set_recent_uploads([upload])
        copy = next(
            button for button in self.plugin.dock.findChildren(QToolButton)
            if button.text() == "Copy link"
        )
        copy.click()
        self.assertEqual(QApplication.clipboard().text(), upload.copy_share_url)
        self.plugin.unload()
        flush_deletes()


def run():
    expected = os.environ["GEODEL_EXPECT_QGIS"]
    expected_qt = os.environ["GEODEL_EXPECT_QT"]
    if not Qgis.QGIS_VERSION.startswith(expected + ".") or not QT_VERSION_STR.startswith(expected_qt + "."):
        print(f"Unexpected runtime: QGIS {Qgis.QGIS_VERSION}, Qt {QT_VERSION_STR}", flush=True)
        return 1
    print(f"Runtime: QGIS {Qgis.QGIS_VERSION}, Qt {QT_VERSION_STR}", flush=True)
    from check_network import NetworkRuntimeTests
    suite = unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromTestCase(PluginRuntimeTests),
        unittest.defaultTestLoader.loadTestsFromTestCase(NetworkRuntimeTests),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/usr"), True)
    application = QgsApplication([], True, os.environ["GEODEL_RUNTIME_ROOT"])
    application.initQgis()
    # Use the supported API; raw settings keys differ between QGIS 3 and 4.
    # This changes only the disposable profile, never the owner's keychain.
    QgsApplication.authManager().setPasswordHelperEnabled(False)
    status = run()
    application.exitQgis()
    sys.exit(status)
