"""Build a deterministic, allowlisted installable plugin ZIP."""

import argparse
from configparser import ConfigParser
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from validate_package import PACKAGE_FILES, validate_package


def build(project, output):
    source = project / "geodel"
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(PACKAGE_FILES):
            info = ZipInfo(f"geodel/{name}", (2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, (source / name).read_bytes(), compresslevel=9)
    validate_package(output, project)
    digest = sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    metadata = ConfigParser()
    metadata.read(project / "geodel/metadata.txt")
    version = metadata["general"]["version"]
    print(build(project, args.output or project / f"dist/geodel-{version}.zip"))


if __name__ == "__main__":
    main()
