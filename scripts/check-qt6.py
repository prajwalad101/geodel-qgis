"""Fail on official checker findings; its dry-run exit code alone is always zero."""
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

project = Path(__file__).resolve().parents[1]
with TemporaryDirectory(prefix="geodel-qt6-check-") as directory:
    report = Path(directory) / "checker.log"
    subprocess.run([
        "pyqt5_to_pyqt6.py", "--dry_run", "--logfile", str(report),
        sys.argv[1] if len(sys.argv) > 1 else str(project / "geodel"),
    ], check=True)
    findings = report.read_text().replace("=== dry_run mode | Start Logs ===", "").strip()
    if findings:
        raise SystemExit(findings)
    print("Official QGIS Qt6 checker: no findings")
