"""Build only the audited installable package, never repository support files."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


PACKAGE_FILES = (
    "__init__.py", "auth_compat.py", "client.py", "config.py", "icon.svg",
    "layer_export.py", "LICENSE", "metadata.txt", "NOTICE.md", "plugin.py",
    "recent_upload.py", "transport.py", "qgis_transport.py", "task_lifecycle.py", "dock.py", "tasks.py", "metadata.py",
)


def main():
    project = Path(__file__).resolve().parents[1]
    source = project / "geodel"
    output = project / "dist" / "geodel.zip"
    missing = [name for name in PACKAGE_FILES if not (source / name).is_file()]
    if missing:
        raise SystemExit(f"Missing required plugin files: {', '.join(missing)}")
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name in PACKAGE_FILES:
            archive.write(source / name, f"geodel/{name}")
    print(output)


if __name__ == "__main__":
    main()
