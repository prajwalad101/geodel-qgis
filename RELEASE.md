# Release candidate and owner handoff

Current candidate: **0.1.1**, stable metadata, QGIS **3.44 through 4.99**.
No final release tag, GitHub publication or QGIS submission is part of #301.
Manual platform testing and QGIS acceptance remain outstanding. GitHub reports
`prajwalad101/geodel-qgis` private as of 2026-10-03; the owner must make the
audited standalone repository public before its metadata links can satisfy
QGIS submission requirements. No visibility change is made by this ticket. Parent #285
is unchanged. Native networking dependency #300 is present in this checkout.

## Reproduce from a clean standalone checkout

Follow CONTRIBUTING.md contributor setup, check out the intended commit, then run:

```sh
scripts/release.sh 0.1.1
```

Output: `dist/geodel-0.1.1.zip` and `dist/geodel-0.1.1.zip.sha256`.
Build uses a fixed file order, timestamp, compression level and permissions.
Identical source with the same Python/zlib toolchain produces identical bytes;
CI uses Python 3.12. The validator checks layout, metadata, production URLs,
assets, size and every packaged file against the selected Git commit.
Only `geodel/` is installed; tests, release tools, repository internals, secrets,
profiles and development dependencies stay outside the archive.

Run the CONTRIBUTING.md Docker commands for both real QGIS runtimes and the official
Qt6 checker. CI runs unit tests, typechecking, Flake8, Bandit and detect-secrets,
then repeats scans and Qt6 checking against the extracted ZIP. Runtime tests
also import the extracted plugin. No production credentials are needed.
Download the candidate artifact from the **Plugin tests** run for the exact
commit; verify its SHA-256 before manual installation. Automated runtime tests do not replace manual platform verification.

## Owner's final steps

1. Confirm all CI jobs passed for the intended commit. Complete a new copy of
   MANUAL_TEST_CHECKLIST.md on supported desktop platforms, QGIS 3.44 LTR and
   latest stable QGIS (including Qt6). Record exact builds, OS versions, tester,
   date, commit, ZIP checksum and actual outcomes. Fix failures and repeat for
   any new candidate commit. Never reuse checked boxes from older tests.
2. Merge the verified commit to `main`. Only after manual signoff, create and
   push annotated tag `v0.1.1` at that exact commit. This is an owner action.
   The tag CI run repeats every required check, validates tag/metadata agreement,
   and creates a **draft** GitHub release with ZIP and SHA-256 assets. It refuses
   existing releases or tags pointing outside main; it uploads only the artifact
   built and verified in that same successful run. Never replace assets by hand.
3. Inspect draft release, matching commit/tag/version/checksum and release notes;
   publish the final GitHub release yourself after manual results are attached.
4. Obtain an OSGeo ID, log in at https://plugins.qgis.org/ and upload the same
   verified ZIP. Supply public source, issue tracker and usage README links.
5. Inspect scan results and reviewer feedback. Resolve blocking findings or
   requested changes in source; build/test a new version and submit again where
   required. Submission is not acceptance. Do not claim acceptance prematurely.
6. After approval, install through the official QGIS Plugin Manager on a clean
   profile and verify version, connection and sample upload/share behavior.
7. Record the accepted Plugin Repository URL and installation verification in
   the execution record. Update README and packaged usage docs with that exact
   URL and official Plugin Manager installation link/instructions. Until then,
   installation links must direct users to verified ZIPs, not an invented listing.

References: [QGIS packaging](https://docs.qgis.org/3.44/en/docs/pyqgis_developer_cookbook/plugins/releasing.html),
[QGIS 4 metadata](https://plugins.qgis.org/docs/migrate-qgis4),
[security checks](https://plugins.qgis.org/docs/security-scanning/tools),
[approval](https://plugins.qgis.org/docs/approval).
