# Contributing

Open issues and pull requests in `prajwalad101/geodel-qgis`. Plugin-only work
belongs here; this is the source of truth, with no submodule or ongoing mirror.
Coordinate service/API changes with GeoDel service maintainers before changing
endpoints, headers, payloads, or minimum supported plugin versions. Do not
assume access to any private repository is needed to contribute here.

Follow README setup, run `.venv/bin/python -m pytest`, compile Python with
`.venv/bin/python -m compileall -q geodel scripts tests`, and build with
`python3 scripts/build.py`. Keep tests and support files outside `geodel/`.
When adding a package file, update the package allowlist in `scripts/validate_package.py`.
Test user-facing behavior; keep fixtures synthetic and independent of services.
Changes affecting QGIS integration must pass the real-runtime tests on QGIS
3.44/Qt5 and 4.2/Qt6 and the official Qt6 checker; see README for commands.
The owner completes the manual checklist before releases on QGIS 3.44 and
latest stable, recording version, OS, date, and actual outcomes.

Never commit secrets, real customer datasets, credential stores, profiles,
generated ZIPs, or dependencies. Preserve copyright and license notices.
New code and resources must be compatible with GPL-3.0-or-later; document
third-party resource provenance and licensing in `geodel/NOTICE.md`.

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
