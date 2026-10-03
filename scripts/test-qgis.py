"""Run the real QGIS/Qt suite with disposable settings and credentials."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

with TemporaryDirectory(prefix='geodel-runtime-') as directory:
    root = Path(directory)
    environment = dict(os.environ)
    for name, folder in (
        ('HOME', 'home'), ('XDG_CONFIG_HOME', 'config'),
        ('XDG_DATA_HOME', 'data'), ('XDG_CACHE_HOME', 'cache'),
        ('QGIS_AUTH_DB_DIR_PATH', 'auth'),
    ):
        path = root / folder
        path.mkdir()
        environment[name] = str(path)
    environment['QT_QPA_PLATFORM'] = 'offscreen'
    environment['GEODEL_RUNTIME_ROOT'] = str(root)
    script = Path(__file__).resolve().parents[1] / 'tests/runtime/check_plugin.py'
    try:
        result = subprocess.run([sys.executable, str(script)], env=environment, timeout=60)
    except subprocess.TimeoutExpired:
        raise SystemExit('QGIS runtime tests exceeded 60 seconds')
    raise SystemExit(result.returncode)
