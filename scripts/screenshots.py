"""Render documentation images from real QGIS widgets with synthetic state.

Run inside a disposable, offline QGIS container; never use a production profile.
These images illustrate the UI, not completed manual platform verification.
"""

import os
from pathlib import Path
import sys

from qgis.core import QgsApplication
from qgis.PyQt.QtGui import QImage, QPainter
from qgis.PyQt.QtSvg import QSvgRenderer
from qgis.PyQt.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geodel.dock import GeoDelDockWidget

root = Path(__file__).resolve().parents[1] / "geodel"
app = QgsApplication([], True)
app.initQgis()
image = QImage(96, 96, QImage.Format.Format_ARGB32)
image.fill(0)
painter = QPainter(image)
QSvgRenderer(str(root / "icon.svg")).render(painter)
painter.end()
assert image.save(str(root / "icon.png"))
dock = GeoDelDockWidget()
dock.resize(560, 940)
dock.show_setup()
dock.show()
QApplication.processEvents()
assert dock.grab().save(str(root / "docs/connection.png"))
dock.set_organizations([{"id": "synthetic", "name": "Demo Workspace"}])
dock.set_folders([])
dock.layers.addItem("Synthetic places")
dock.layers.item(0).setSelected(True)
dock.upload_name.setText("Synthetic places")
dock.show_connected()
QApplication.processEvents()
assert dock.grab().save(str(root / "docs/uploads.png"))
dock.close()
app.exitQgis()
# Qt object destruction after QGIS shutdown can crash in some container builds.
sys.stdout.flush()
os._exit(0)
