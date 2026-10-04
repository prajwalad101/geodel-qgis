# Standalone snapshot audit

## Scope and method

Reviewed every exported Python module, behavior test, script, documentation
file, metadata field, and SVG before publication. The initial history contains
only the audited package and standalone support files. No earlier history,
service code, environment files, QGIS profiles, binaries, real datasets, or
archives are included. The interrupted prototype was not used.

Reviewed imports, filesystem paths, network destinations, credential handling,
fixture values, and resource notices; searched for private-key blocks, common
credential prefixes, personal addresses, machine paths, and signed URLs.
This is a source and resource audit, not a claim that the plugin has had a
complete runtime security assessment.

## Findings and resolutions

- Production API/website URLs, public repository URLs, and
  `hello@geodel.app` are intentional public configuration/support details.
- Test credentials such as `geodel_secret`, `geodel_revoked`, and `key` are
  synthetic placeholders passed to mocked sessions. Organization IDs,
  filenames, coordinates, and example.com URLs are synthetic; no customer
  data or usable credentials were found.
- The original icon depended on web artwork without a documented resource
  license. Replaced it with an original SVG globe under GPL-3.0-or-later.
  Icon tests now validate the resource shipped with the plugin.
- Preserved the GeoDel contributor copyright and GPL-3.0-or-later grant;
  included the complete GNU GPL v3 text in repository and package LICENSE.
  `geodel/NOTICE.md` records resource provenance and external dependencies.
- QGIS/Qt provide the runtime, including networking; no additional runtime
  Python packages are required. Development scan tools depend on requests,
  which is not included in the plugin ZIP.
  No third-party fixture data or artwork is shipped.
- Standalone support files replace the previous history-export tooling.
  Release tooling pushes only this repository's history; it is not run as
  part of extraction. Build tooling explicitly lists installable files.
- Minimum QGIS version is 3.44. Plugin version stays 0.1.0. Service API
  compatibility and service minimum plugin version are unchanged.

## Verification boundary

The original baseline and standalone behavior suite each contain 40 tests.
Clean-clone verification and ZIP inspection are recorded by the extraction
maintainer. The manual QGIS checklist is reset to unchecked: QGIS 3.44 and
latest-stable installation, GUI, and live-service checks remain required before
a final release. No final release or QGIS submission accompanies this snapshot.
