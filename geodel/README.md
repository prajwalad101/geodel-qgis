# GeoDel QGIS 0.1.1

Upload and share vector data from QGIS 3.44–4.x. GeoDel provides online storage,
processing and share links; this plugin connects your project to that service.
No additional runtime Python packages are required.

## Requirements and setup

Live operations require a GeoDel account, a Workspace, a Personal API Key,
an internet connection, and an active GeoDel trial or subscription with enough
storage/upload allowance. Service plans and account permissions apply; the
plugin license does not provide a service subscription.

Install the ZIP in **Plugins > Manage and Install Plugins > Install from ZIP**.
Open **Web > GeoDel**, choose **Open API Key Setup**, sign in to GeoDel, create
and copy a Personal API Key, paste it into the masked field, then choose
**Save and connect**. QGIS Authentication Manager encrypts the key and may ask
you to set or unlock its master password. Keep that password available.

## Upload and share

Choose your Workspace and destination folder (or Files root). Select 1–20
vector layers from the current QGIS project and edit the upload name. One layer
exports as GeoJSON; multiple layers export as a ZIP of Shapefiles. Project
exports use EPSG:4326. Empty layers and raster layers are unsupported.
Shapefile field-name/type limitations apply to multi-layer exports.

Use **Browse…** to upload an existing `.geojson`, `.json`, or `.zip` unchanged
(the ZIP should contain supported vector data such as Shapefiles). File
extensions alone do not guarantee valid data; GeoDel validates/processes the
contents. Maximum upload size is **200 MiB (209,715,200 bytes)**, shown as 200 MB
in the panel. Limit applies to the final file, including project exports.
Choose **Cancel upload** during layer preparation or transfer to stop the task.
Wait for cancellation to finish before retrying; the selected source and name
are retained. A file already registered with GeoDel remains in Recent uploads.
Files up to 100 MiB use one streamed PUT; larger files upload three 10 MiB
parts concurrently. Part-signing requests and storage PUTs retry temporary
network/server failures up to three times with a short delay. Initialization,
completion and registration requests do not retry. Each transfer attempt can
take up to five minutes; QGIS network inactivity settings also apply. Progress
reaches 100% after registration. Once registration starts, cancellation waits
for its result (up to 15 seconds); a successful registration remains uploaded.
Names cannot contain `/`.

Upload runs in QGIS Task Manager. Recent uploads refresh while the panel is
open. When ready, choose **Copy link** in the list or **Copy share link** in
the notification. Verify the destination and sharing permissions on GeoDel
before distributing a link. Failed layers and health warnings link to details
on the website. See [synthetic sample](sample/README.md) for a safe first test.

## Data transfer and credentials

Connecting sends your Personal API Key over HTTPS to `https://api.geodel.app`
for account/Workspace validation and API requests. API requests also send the
plugin version and selected Workspace identifier where needed. Upload sends
the selected file, or exported vector geometries and attributes, to GeoDel's
signed storage URLs. GeoDel processes/stores those data and supplies upload
status, folder, Workspace and sharing information. Uploaded data leave your
computer; choose only data you are authorized to transfer. Browse sends the
whole selected file unchanged. No other project layers are uploaded.

API keys are encrypted in QGIS Authentication Manager; settings store the
configuration ID and workspace/folder preferences. Signed storage requests
never carry the GeoDel API key. Copying a link places it on the clipboard;
opening setup/details links launches your browser. Sharing links can grant
access to uploaded data; handle them according to your data policy.

Networking honors QGIS proxy and TLS settings. API calls have a 15-second
deadline; signed-storage requests have a five-minute deadline per attempt. Cancel from QGIS
Task Manager; canceled/failed multipart transfers attempt server cleanup.
Canceled/failed single-PUT attempts rely on server expiration and cleanup;
their temporary storage reservation may remain until then.
GeoDel retains uploaded files according to service/account settings; manage
or delete files in the web app. See GeoDel's current service terms/privacy
information before uploading sensitive data.

## Troubleshooting

- Invalid/revoked key: create a new Personal API Key, then use **Connection
  management** to replace it. Never include keys or signed links in bug reports.
- No Workspace: create one through **Set up a Workspace**, then **Refresh**.
- Trial/subscription or permission failure: check your account plan, Workspace
  membership and allowance on GeoDel; retry after correcting them.
- Connection timeout/proxy/TLS failure: check internet and QGIS network settings,
  trusted certificates and proxy credentials. Background tasks cannot prompt
  for interactive certificate or HTTP authentication approval. Do not disable
  TLS verification. Refresh after correcting settings.
- Authentication Manager locked: unlock with the QGIS master password. Consult
  QGIS guidance before resetting its store; resetting can remove other credentials.
- Upload rejected: check supported formats, nonempty vectors, 20-layer limit,
  final file size and upload name. Inspect processing details in GeoDel.
- Update required: obtain the newer plugin version when the service requires it.

Source and usage: https://github.com/prajwalad101/geodel-qgis
Bug reports: https://github.com/prajwalad101/geodel-qgis/issues
Include plugin version, exact QGIS build, OS, steps and sanitized error text.
This candidate has not been accepted into the official QGIS Plugin Repository.
Use ZIP installation until an accepted Plugin Repository URL is recorded.

## License and resources

Copyright (C) 2026 GeoDel contributors. Code, tests, scripts, and documentation
are distributed under GPL-3.0-or-later; see LICENSE.

The two-point sample dataset is invented by GeoDel contributors and is
GPL-3.0-or-later. No third-party datasets are bundled.

QGIS and Qt, including native networking, are supplied by the user's QGIS
installation. They are not bundled or relicensed by this repository. Their
respective licenses continue to apply. GeoDel is the product name; this license
does not grant trademark rights.
