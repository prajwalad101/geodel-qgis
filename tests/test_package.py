"""Exercise the release ZIP boundary using tampered archives and source."""
from pathlib import Path
import shutil
import sys
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build import build
from validate_package import validate_package

PROJECT = Path(__file__).resolve().parents[1]


def rewrite(path, change):
    with ZipFile(path) as archive:
        entries = [(item, archive.read(item)) for item in archive.infolist()]
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for item, data in entries:
            data = change(item.filename, data)
            if data is not None:
                archive.writestr(item, data)


def test_candidate_is_reproducible_and_checksum_matches(tmp_path):
    first = build(PROJECT, tmp_path / "one.zip")
    second = build(PROJECT, tmp_path / "two.zip")
    assert first.read_bytes() == second.read_bytes()
    assert validate_package(first, PROJECT, tag="v0.1.1") == "0.1.1"
    import hashlib
    assert first.with_suffix(".zip.sha256").read_text() == (
        f"{hashlib.sha256(first.read_bytes()).hexdigest()}  one.zip\n"
    )


@pytest.mark.parametrize("name", [
    "geodel/.env", "geodel/__pycache__/client.pyc", "../private.txt",
    "tests/test_client.py", "geodel/customer.geojson",
])
def test_rejects_unexpected_files(tmp_path, name):
    path = build(PROJECT, tmp_path / "candidate.zip")
    with ZipFile(path, "a") as archive:
        archive.writestr(name, "unexpected")
    with pytest.raises(ValueError, match="allowlisted"):
        validate_package(path, PROJECT)


@pytest.mark.parametrize("name", ["geodel/icon.png", "geodel/LICENSE", "geodel/client.py"])
def test_rejects_missing_assets_license_and_source(tmp_path, name):
    path = build(PROJECT, tmp_path / "candidate.zip")
    rewrite(path, lambda entry, data: None if entry == name else data)
    with pytest.raises(ValueError, match="allowlisted"):
        validate_package(path, PROJECT)


def test_rejects_tampered_source(tmp_path):
    path = build(PROJECT, tmp_path / "candidate.zip")
    rewrite(path, lambda name, data: data + b"\n# tampered\n" if name.endswith("client.py") else data)
    with pytest.raises(ValueError, match="differs from source"):
        validate_package(path, PROJECT)


def test_rejects_mismatched_tag(tmp_path):
    path = build(PROJECT, tmp_path / "candidate.zip")
    with pytest.raises(ValueError, match="tag must match"):
        validate_package(path, PROJECT, tag="v0.1.0")


def test_rejects_development_urls_even_when_matching_checkout(tmp_path):
    project = tmp_path / "checkout"
    shutil.copytree(PROJECT / "geodel", project / "geodel", ignore=shutil.ignore_patterns("__pycache__"))
    config = project / "geodel/config.py"
    config.write_text(config.read_text().replace("https://api.geodel.app", "http://localhost:4000"))
    with pytest.raises(ValueError, match="service URLs"):
        build(project, tmp_path / "candidate.zip")


def test_rejects_oversize_archive(tmp_path):
    path = build(PROJECT, tmp_path / "candidate.zip")
    with path.open("ab") as stream:
        stream.truncate(25 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="exceeds 25 MB"):
        validate_package(path, PROJECT)
