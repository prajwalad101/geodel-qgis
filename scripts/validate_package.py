"""Validate release layout, metadata, production configuration and source bytes."""

import argparse
import ast
from configparser import ConfigParser
from pathlib import Path
import re
import subprocess
from zipfile import ZipFile

PACKAGE_FILES = (
    "__init__.py", "auth_compat.py", "client.py", "config.py", "icon.svg",
    "icon.png", "layer_export.py", "LICENSE", "metadata.txt", "NOTICE.md",
    "plugin.py", "recent_upload.py", "transport.py", "qgis_transport.py",
    "task_lifecycle.py", "dock.py", "tasks.py", "metadata.py", "README.md",
    "docs/connection.png", "docs/uploads.png", "sample/places.geojson",
    "sample/README.md",
)
MAX_ARCHIVE_SIZE = 25_000_000
REPOSITORY = "https://github.com/prajwalad101/geodel-qgis"


def validate_package(path, project, tag=None, commit=None):
    if path.stat().st_size > MAX_ARCHIVE_SIZE:
        raise ValueError("Archive exceeds 25 MB")
    with ZipFile(path) as archive:
        names = archive.namelist()
        expected = {f"geodel/{name}" for name in PACKAGE_FILES}
        if len(names) != len(expected) or set(names) != expected:
            raise ValueError("Package must contain exactly the allowlisted plugin files")
        if sum(info.file_size for info in archive.infolist()) > MAX_ARCHIVE_SIZE:
            raise ValueError("Expanded package exceeds 25 MB")
        for info in archive.infolist():
            if info.external_attr >> 16 != 0o100644:
                raise ValueError(f"Unexpected file permissions: {info.filename}")
        metadata = ConfigParser()
        metadata.read_string(archive.read("geodel/metadata.txt").decode())
        general = metadata["general"]
        for key in ("name", "description", "about", "author", "email", "tags", "changelog"):
            if not general.get(key, "").strip():
                raise ValueError(f"Missing required metadata: {key}")
        for key, value in {
            "qgisMinimumVersion": "3.44", "qgisMaximumVersion": "4.99",
            "experimental": "False", "icon": "icon.png",
            "repository": REPOSITORY, "tracker": REPOSITORY + "/issues",
            "homepage": REPOSITORY + "/blob/main/README.md",
        }.items():
            if general.get(key) != value:
                raise ValueError(f"Invalid release metadata: {key}")
        version = general.get("version", "")
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ValueError("Invalid stable version")
        if "supportsQt6" in general:
            raise ValueError("Obsolete supportsQt6 metadata")
        if tag is not None and tag != f"v{version}":
            raise ValueError("Release tag must match metadata version")
        tree = ast.parse(archive.read("geodel/config.py"))
        urls = {
            node.target.id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
            and node.value is not None and node.target.id in ("API_URL", "WEB_URL")
        }
        if urls != {"API_URL": "https://api.geodel.app", "WEB_URL": "https://geodel.app"}:
            raise ValueError("Development or unexpected service URLs")
        for name in ("icon.png", "docs/connection.png", "docs/uploads.png"):
            if not archive.read(f"geodel/{name}").startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError(f"Invalid PNG asset: {name}")
        if b"GNU GENERAL PUBLIC LICENSE" not in archive.read("geodel/LICENSE"):
            raise ValueError("Missing GPL license")
        for name in PACKAGE_FILES:
            if commit:
                source = subprocess.run(
                    ["git", "show", f"{commit}:geodel/{name}"], cwd=project,
                    check=True, capture_output=True,
                ).stdout
            else:
                source = (project / "geodel" / name).read_bytes()
            if archive.read(f"geodel/{name}") != source:
                raise ValueError(f"Packaged file differs from source: {name}")
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--tag")
    parser.add_argument("--commit", help="Compare every packaged file with this Git commit")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    version = validate_package(args.archive, project, args.tag, args.commit)
    print(f"Validated GeoDel {version}: {args.archive}")


if __name__ == "__main__":
    main()
