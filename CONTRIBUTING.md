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

## Backend metadata

`GET /api/v1/meta` is public and receives `X-Plugin-Version`. It returns
`minPluginVersion`, the echoed `pluginVersion`, and an optional `qgisPlugin`
object with `schemaVersion: 1`. No API key or Workspace is needed. The service
keeps its existing `Cache-Control: private, no-store` policy.

| Field | Packaged default | Accepted values |
|---|---|---|
| `maxFileSizeBytes` | 209715200 | Positive integer, no more than `partSizeBytes × 10000` |
| `maxProjectLayers` | 20 | Integer 1–10000 |
| `maxFilenameLength` | 255 | Integer 1–10000, measured in JavaScript UTF-16 code units |
| `allowedExtensions` | `[".zip", ".geojson", ".json"]` | Nonempty array of lowercase extensions; only installed handlers are enabled |
| `singlePutThresholdBytes` | 104857600 | Integer from `partSizeBytes` to 5 GiB |
| `partSizeBytes` | 10485760 | Integer from 5 MiB to 64 MiB |
| `partConcurrency` | 3 | Integer 1–8; `partSizeBytes × partConcurrency` must not exceed 256 MiB |
| `retryDelaysSeconds` | `[1, 3, 5]` | Array of up to five integers from 0 to 30; an empty array disables retries |
| `requestTimeoutSeconds` | 15 | Integer 1–60 |
| `uploadPartTimeoutSeconds` | 300 | Integer 1–3600 |
| `processingTimeoutSeconds` | 600 | Integer 1–7200 |
| `recentUploadsRefreshSeconds` | 5 | Integer 1–300 |
| `connectionFeedbackTimeoutSeconds` | 5 | Integer 1–60 |

All fields are required when `qgisPlugin` is present. Unknown fields are
ignored. Unsupported schema versions and malformed configuration are rejected
as a whole; the minimum-version notice is handled independently. Missing
configuration on an older API retains the active settings. The plugin retains
its last valid configuration in memory or uses packaged defaults; it does not
persist configuration to QGIS settings. If the server advertises only formats
that the installed plugin cannot handle, uploads are disabled.

In the backend repository, update the shared upload/layer/name/extension
constants for policy and `QGIS_PLUGIN_CONFIG` in API configuration for tuning.
The metadata size derives from `MAX_FILE_SIZE_KB × 1024`; change the shared
limit rather than overriding only the advertised size. Deploy API and worker
changes together when changing shared policy. Deploy the additive metadata API
before releasing this plugin. Older plugin installations keep their packaged
limits until upgraded.

Metadata loads at initialization, panel opening, manual Refresh, and every
five minutes while visible. Requests do not overlap. Configuration is copied
by reference as an immutable snapshot into layer preparation and upload tasks;
refreshes never modify an active upload. Backend validation remains authoritative,
so a lowered limit can reject an upload started with older settings.

API/Web origins, export CRS/implementation, credentials, network security,
and the five-minute metadata refresh cadence remain packaged. Feature switches,
maintenance notices, and editable admin settings are deferred. Metadata changes
cannot add a parser, UI workflow, or execute downloaded code.

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
