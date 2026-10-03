# GeoDel QGIS plugin

Standalone public home for GeoDel QGIS plugin development. Requires **QGIS
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
```

On Windows, use `py` instead of `python3` and `.venv\Scripts\python.exe`
instead of `.venv/bin/python`. Development dependencies and their transitive
dependencies are pinned in `requirements-dev.txt`. The 40 behavior tests use
synthetic fixtures and QGIS doubles; they do not need QGIS, network access,
or any other repository. They do not replace runtime checks in QGIS.

`geodel/` is the installable Python package. Tests, scripts, and documentation
live outside it. The build script includes only the audited package files in
`dist/geodel.zip`, including the entry point, metadata, license, and resource
notices. Generated archives are ignored and must not be committed.

## QGIS installation and use

The plugin imports `requests`, which is not bundled. If your QGIS Python
console cannot `import requests`, install it into **QGIS's Python environment**
using that installation's Python executable and `-m pip install requests==2.34.2`.
The development virtual environment does not install packages into QGIS.
QGIS supplies the `qgis` and `qgis.PyQt` modules; do not install separate Qt
bindings into the plugin.

Install `dist/geodel.zip` through **Plugins → Manage and Install Plugins →
Install from ZIP**. Open GeoDel from its toolbar icon, choose **Open API Key
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
`http://localhost:4000` and `WEB_URL` to `http://localhost:3000`, then rebuild.
The ZIP includes this file: restore production URLs before sharing a build.
Never commit Personal API Keys, QGIS profiles, customer data, or signed URLs.

## Contributions and releases

See [CONTRIBUTING.md](CONTRIBUTING.md) for coordination and triage, and
[AUDIT.md](AUDIT.md) for the public snapshot audit. Plugin-only changes belong
here. Service/API changes require coordination with GeoDel service maintainers.
The service owns its API contract and minimum supported plugin version;
repository extraction does not change either.

Before a release, complete [MANUAL_TEST_CHECKLIST.md](MANUAL_TEST_CHECKLIST.md)
on QGIS 3.44 and the latest stable QGIS release and record actual results.
From a clean `main` commit with matching `geodel/metadata.txt` version and
standalone `origin`, maintainers may run:

```sh
scripts/release.sh 0.1.0
```

This tests, builds the local ZIP, and atomically pushes the standalone source
and annotated version tag. It does not create a GitHub release or submit to
QGIS. No release or QGIS submission was made for this extraction. Public source,
license, and resource requirements are documented by
[QGIS](https://plugins.qgis.org/docs/publish).

## License

GPL-3.0-or-later, Copyright (C) 2026 GeoDel contributors.
Complete license text is in [LICENSE](LICENSE) and `geodel/LICENSE`.
Resource and dependency notices are in [geodel/NOTICE.md](geodel/NOTICE.md).
