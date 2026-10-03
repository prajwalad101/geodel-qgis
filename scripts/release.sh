#!/usr/bin/env bash
set -euo pipefail

version=${1:?Usage: scripts/release.sh VERSION}
root=$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)
cd "$root"
metadata_version=$(sed -n 's/^version=//p' geodel/metadata.txt)

if [[ "$version" != "$metadata_version" || ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Release version must match metadata version $metadata_version" >&2
  exit 1
fi
if [[ $(git branch --show-current) != main || -n $(git status --porcelain) ]]; then
  echo "Release from a clean, committed main branch" >&2
  exit 1
fi
if [[ $(git remote get-url origin) != https://github.com/prajwalad101/geodel-qgis.git &&
      $(git remote get-url origin) != git@github.com:prajwalad101/geodel-qgis.git ]]; then
  echo "Origin must be the standalone geodel-qgis repository" >&2
  exit 1
fi

# Run after completing MANUAL_TEST_CHECKLIST.md for this version.
.venv/bin/python -m pytest
python3 scripts/build.py
git tag -a "v$version" -m "GeoDel QGIS plugin $version"
git push --atomic origin HEAD:refs/heads/main "refs/tags/v$version"

echo "Pushed source and tag; ZIP remains local at $root/dist/geodel.zip"
echo "QGIS submission and GitHub releases are separate manual steps."
