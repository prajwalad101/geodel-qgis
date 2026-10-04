"""Render the plugin PNG icon from its retained SVG using QGIS Qt.

Run inside an offline QGIS container with QT_QPA_PLATFORM=offscreen.
"""

import os
from pathlib import Path
import sys

from qgis.core import QgsApplication
from qgis.PyQt.QtGui import QImage, QPainter
from qgis.PyQt.QtSvg import QSvgRenderer

root = Path(__file__).resolve().parents[1] / "geodel"
app = QgsApplication([], True)
app.initQgis()
image = QImage(96, 96, QImage.Format.Format_ARGB32)
image.fill(0)
painter = QPainter(image)
QSvgRenderer(str(root / "icon.svg")).render(painter)
painter.end()
assert image.save(str(root / "icon.png"))
app.exitQgis()
# Qt object destruction after QGIS shutdown can crash in some container builds.
sys.stdout.flush()
os._exit(0)
