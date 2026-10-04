# Contributing

Open issues and pull requests in `prajwalad101/geodel-qgis`. Plugin-only work
belongs here; this is the source of truth, with no submodule or ongoing mirror.
Coordinate service/API changes with GeoDel service maintainers before changing
endpoints, headers, payloads, or minimum supported plugin versions. Do not
assume access to any private repository is needed to contribute here.

Follow the contributor setup below, run `.venv/bin/python -m pytest`, compile Python with
`.venv/bin/python -m compileall -q geodel scripts tests`, and build with
`python3 scripts/build.py`. Keep tests and support files outside `geodel/`.
When adding a package file, update the package allowlist in `scripts/validate_package.py`.
Test user-facing behavior; keep fixtures synthetic and independent of services.
Changes affecting QGIS integration must pass the real-runtime tests on QGIS
3.44/Qt5 and 4.2/Qt6 and the official Qt6 checker; see the runtime commands below.
Before releasing, manually verify installation, connection, upload and sharing
on QGIS 3.44 and latest stable. Record the tested version, OS and outcomes in
the release notes.

Never commit secrets, real customer datasets, credential stores, profiles,
generated ZIPs, or dependencies. Preserve copyright and license notices.
New code and resources must be compatible with GPL-3.0-or-later; document
third-party resource provenance and licensing in `geodel/README.md`.

## Contributor setup and checks

Install Python 3.10 or newer and Git, then:

```sh
git clone https://github.com/prajwalad101/geodel-qgis.git
cd geodel-qgis
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
python3 scripts/build.py
.venv/bin/python scripts/scan.py geodel
.venv/bin/python -m mypy --check-untyped-defs scripts/build.py scripts/validate_package.py scripts/scan.py
```

On Windows, use `py` instead of `python3` and `.venv\Scripts\python.exe`
instead of `.venv/bin/python`. Tests use synthetic data and require no GeoDel
account or production credentials. CI checks QGIS 3.44/Qt5 and 4.2/Qt6 in
isolated profiles. Run locally with Docker (add `--platform linux/amd64` on
Apple Silicon):

```sh
docker run --rm --network none --entrypoint python3 \
  -v "$PWD:/workspace:ro" -w /workspace \
  -e GEODEL_EXPECT_QGIS=3.44 -e GEODEL_EXPECT_QT=5 \
  qgis/qgis@sha256:bacafbaf899bb2af5d99dd8a138e0438733aac252ddd5f29d089ad34641bb059 \
  scripts/test-qgis.py

docker run --rm --network none --entrypoint python3 \
  -v "$PWD:/workspace:ro" -w /workspace \
  -e GEODEL_EXPECT_QGIS=4.2 -e GEODEL_EXPECT_QT=6 \
  qgis/qgis@sha256:8996496c15887a8fae0da05fa38103093ddbf104525bcbd67bf733a914fb1444 \
  scripts/test-qgis.py

docker run --rm --network none --entrypoint python3 \
  -v "$PWD:/workspace:ro" -w /workspace \
  ghcr.io/qgis/pyqgis4-checker@sha256:c96df111845eb0c86ad56364fb792d35fa6931e01d3d629d2b1bc6388ed43ece \
  scripts/check-qt6.py
```

The official Qt6 checker fails when its dry-run report contains findings.
See [release handoff](RELEASE.md) for package verification and publication steps.

## Local service development

For a local service, change `API_URL` and `WEB_URL` in `geodel/config.py`.
Copy `geodel/` into the Python plugins directory of a separate disposable QGIS
profile and restart that profile. Release builds reject development URLs;
restore production URLs before building a candidate. Keep production credentials
out of local service testing.

## Issue triage

Use these five canonical triage labels:

- `needs-triage`: needs evaluation.
- `needs-info`: waiting on reporter.
- `ready-for-agent`: ready for an agent.
- `ready-for-human`: ready for a human.
- `wontfix`: will not be actioned.

Maintainers can recreate the labels using `scripts/setup-labels.sh` with an
authenticated GitHub CLI. Issues and PRDs use GitHub Issues; pull requests are
for proposed changes, not triage intake.

## Dependency updates

Edit `requirements-dev.in`, then regenerate the complete cross-platform pins:

```sh
uv pip compile --universal requirements-dev.in -o requirements-dev.txt
```

Install the updated pins into a fresh virtual environment and run the suite.
Runtime networking must use QGIS APIs; do not add a separate HTTP library.
