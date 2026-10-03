#!/usr/bin/env bash
set -euo pipefail

# Local candidate verification only: never create/push tags or publish releases.
version=${1:?Usage: scripts/release.sh VERSION}
root=$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)
cd "$root"
if [[ -n $(git status --porcelain) ]]; then
  echo "Candidate requires a clean committed checkout" >&2
  exit 1
fi
.venv/bin/python -m pytest
.venv/bin/python -m mypy --check-untyped-defs scripts/build.py scripts/validate_package.py scripts/scan.py
.venv/bin/python scripts/build.py --output "dist/geodel-$version.zip"
.venv/bin/python scripts/validate_package.py "dist/geodel-$version.zip" --tag "v$version" --commit HEAD
.venv/bin/python scripts/scan.py geodel
extract=$(mktemp -d)
trap 'rm -rf "$extract"' EXIT
.venv/bin/python -m zipfile -e "dist/geodel-$version.zip" "$extract"
.venv/bin/python scripts/scan.py "$extract/geodel"
echo "Candidate: dist/geodel-$version.zip and .zip.sha256"
echo "Owner must verify CI and complete fresh manual records before tagging."
