# GeoDel QGIS plugin

Standalone home for GeoDel QGIS plugin development. Requires **QGIS
3.44 or newer**, a GeoDel account, a Workspace, and a Personal API Key for
live operations. Testing and building require no account or service access.

## Contributor setup

Install Python 3.10 or newer and Git, then:

```sh
git clone https://github.com/prajwalad101/geodel-qgis.git
cd geodel-qgis
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
python3 scripts/build.py
.venv/bin/python scripts/scan.py geodel
.venv/bin/python -m mypy scripts/build.py scripts/validate_package.py scripts/scan.py
```

On Windows, use `py` instead of `python3` and `.venv\Scripts\python.exe`
instead of `.venv/bin/python`. Development dependencies and their transitive
dependencies are pinned in `requirements-dev.txt`. The behavior tests use
synthetic fixtures and QGIS doubles; they do not need QGIS, network access,
or any other repository. QGIS integration tests run separately in real QGIS/Qt runtimes. They use a
small interface host backed by real Qt menus, toolbar, dock widgets, QGIS tasks
and Authentication Manager. Network tests use controlled local HTTP, proxy,
and self-signed TLS fixtures, including redirects, credential/cache isolation,
deadlines, cancellation, and cleanup. Lifecycle tests use synthetic service
responses. They cover
entry-point loading, repeated GUI initialization, open/close, unload/reload,
cancellation and late callbacks, encrypted key replacement, and share-link copy.

CI runs QGIS 3.44 with Qt5 and QGIS 4.2 with Qt6 using pinned official container
images. Each run has a disposable home, settings profile and authentication
store, disables the password helper through QGIS's API, and disables container
network access. It never touches your QGIS profile or operating-system keychain.
Run locally with Docker (add `--platform linux/amd64` on Apple Silicon):

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

The official checker runs in dry-run mode; its report is checked for findings
because its exit status alone does not indicate compatibility. See the
[QGIS migration guidance](https://github.com/qgis/QGIS/wiki/Plugin-migration-to-be-compatible-with-Qt5-and-Qt6).
Runtime tests supplement the owner's manual release checklist.

`geodel/` is the installable Python package. Development tests and release scripts live outside it; installable usage docs
and original sample/assets live inside it. The build script includes only the audited package files in
`dist/geodel-0.1.1.zip`, including the entry point, metadata, license, and resource
notices. Generated archives are ignored and must not be committed.

## Usage, requirements and troubleshooting

See [packaged usage guide](geodel/README.md) for setup, screenshots, vector
upload/share behavior, troubleshooting and data-transfer disclosure. Live use
requires an account, Workspace, Personal API Key, internet and an active trial
or subscription. Limits: 20 project vector layers and 60 MiB per upload. Browse
supports `.zip`, `.geojson` and `.json`. [Synthetic sample](geodel/sample/README.md)
is included under GPL-3.0-or-later. No extra runtime Python packages needed.

## QGIS installation and use

Networking uses QGIS's native `QgsBlockingNetworkRequest` inside background
tasks, honoring QGIS proxy, TLS, and network settings. No extra Python runtime
packages are required. QGIS supplies the `qgis` and `qgis.PyQt` modules; do not
install separate Qt bindings into the plugin.

API calls have a 15-second deadline and signed-storage transfers have a
60-second deadline. Cancellation aborts active requests; failed or canceled
multipart uploads attempt cleanup with an independent 15-second deadline.
Authenticated responses bypass cache. API redirects may stay on the same
origin; cross-origin API redirects and HTTPS downgrades are refused. Signed
storage requests and their redirects never carry GeoDel authentication,
organization, or plugin-version headers. Request failures contain no submitted
Personal API Key. Configure trusted certificates and proxy credentials in
QGIS settings; background requests fail without interactive TLS or HTTP login
prompts so their deadlines and cancellation remain effective.

Install `dist/geodel-0.1.1.zip` through **Plugins → Manage and Install Plugins →
Install from ZIP**. Open GeoDel from **Web → GeoDel** or its Web toolbar icon, choose **Open API Key
Setup**, create and copy a Personal API Key, then paste it into the panel and
choose **Save and connect**. GeoDel validates the key before unlocking
operations. The key is encrypted by QGIS Authentication Manager. The
authentication-config ID and one-time master-password explanation flag use
`QgsSettings`; the API key never does.
Once connected, open **Connection management** to refresh or replace the key,
then choose **Back to uploads** to return.

Choose one or more vector layers from the current project, then edit the
pre-filled name and upload. Single layers export as GeoJSON; multiple layers
export as zipped Shapefiles. Exports use EPSG:4326 and run in QGIS Task Manager.
Use **Browse…** instead to upload an existing `.zip`, `.geojson`, or `.json`
file unchanged. Ready uploads show a **Copy share link** action in the message
bar. The panel's recent-upload list refreshes every five seconds while open,
with failed-layer and health-warning summaries linking to the web app.

## Local service development

The plugin reads its product name, API URL, and website URL from
`geodel/config.py`. For a local service, set `API_URL` to
`http://localhost:4000` and `WEB_URL` to `http://localhost:3000`. For this
development-only setup, copy the `geodel/` directory directly into the Python
plugins directory of a separate disposable QGIS profile, then restart that
profile. Release builds reject local URLs; restore production URLs before
building or sharing a candidate. Never use your normal credential profile for
local service testing.
Release validation rejects development service URLs. Never commit Personal API
Keys, QGIS profiles, customer data, or signed URLs.

## Contributions and releases

See [CONTRIBUTING.md](CONTRIBUTING.md) for coordination and triage, and
[AUDIT.md](AUDIT.md) for the public snapshot audit. Plugin-only changes belong
here. Service/API changes require coordination with GeoDel service maintainers.
The service owns its API contract and minimum supported plugin version;
repository extraction does not change either.

See [RELEASE.md](RELEASE.md) for reproducible candidate verification, CI gates,
tag-based draft packaging and owner publication/submission steps. No manual
platform test or QGIS acceptance is claimed. Current candidate is 0.1.1.

## License

GPL-3.0-or-later, Copyright (C) 2026 GeoDel contributors.
Complete license text is in [LICENSE](LICENSE) and `geodel/LICENSE`.
Resource and dependency notices are in [geodel/NOTICE.md](geodel/NOTICE.md).
