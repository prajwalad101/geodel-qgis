# GeoDel for QGIS

[GeoDel](https://geodel.app) lets you upload, organize, and share vector GIS data
online. This plugin connects your QGIS project to a GeoDel Workspace so you can
upload layers and copy share links without leaving QGIS.

## Requirements

- **QGIS 3.44–4.x**. No additional Python packages are needed.
- A GeoDel account, a Workspace, and a Personal API Key.
- An internet connection and an active GeoDel trial or subscription with
  enough storage and upload allowance.

## Install and connect

Version **0.1.1** is a release candidate. Official QGIS Plugin Repository
acceptance and manual platform verification are pending; use ZIP installation.

1. Obtain the verified `geodel-0.1.1.zip` from the candidate's successful
   [GitHub Actions run](https://github.com/prajwalad101/geodel-qgis/actions).
   Check its accompanying SHA-256 checksum. Contributors can build it locally
   using [these instructions](CONTRIBUTING.md#contributor-setup-and-checks).
2. In QGIS, open **Plugins > Manage and Install Plugins > Install from ZIP**
   and select the ZIP.
3. Open **Web > GeoDel** or use the GeoDel toolbar icon.
4. Choose **Open API Key Setup**, sign in to GeoDel, and create a Personal API Key.
5. Paste the key into the panel and choose **Save and connect**. QGIS may ask
   you to set or unlock its Authentication Manager master password.

## Upload and share

1. Choose your Workspace and destination folder.
2. Select vector layers from your QGIS project, or use **Browse…** to select a file.
3. Review the upload name and choose **Upload to GeoDel**.
4. When processing finishes, choose **Copy link** in recent uploads or
   **Copy share link** in the notification. Check sharing permissions in GeoDel
   before distributing the link.

One project layer exports as **GeoJSON**; multiple layers export as **zipped
Shapefiles**, using EPSG:4326. Browse uploads `.geojson`, `.json`, or `.zip`
files unchanged. Limits are **20 project layers** and **200 MiB per upload**
(shown as 200 MB in the panel). Raster and empty layers are unsupported.
Files up to 100 MiB use a single streamed transfer; larger files upload three
10 MiB parts concurrently. Temporary transfer failures retry automatically.

Choose **Cancel upload** to stop layer preparation or a file transfer. Wait for
cancellation to finish before retrying. Already registered files remain in
Recent uploads.

Try the [licensed synthetic sample](geodel/sample/README.md) for your first upload.

## Data and privacy

Uploads send the selected file, or exported vector geometries and attributes,
to GeoDel's online storage for processing and sharing. Upload only data you
are authorized to transfer. Manage sharing and delete uploaded data in GeoDel.
QGIS Authentication Manager stores your API key encrypted. Never include keys
or share links in bug reports. See the [full data-transfer disclosure](geodel/README.md#data-transfer-and-credentials).

## Help

- **Cannot connect:** check your key, internet connection, and QGIS proxy/TLS settings.
- **No Workspace:** create one using **Set up a Workspace**, then **Refresh**.
- **Upload fails:** check file format, layer count, size, and your account allowance.

See the [usage and troubleshooting guide](geodel/README.md) for more help.
[Report a problem](https://github.com/prajwalad101/geodel-qgis/issues) with your
plugin version, QGIS build, OS, and steps to reproduce.

## Development and license

[Contributing](CONTRIBUTING.md) · [Release verification](RELEASE.md)

GPL-3.0-or-later. See [LICENSE](LICENSE) and [resource attribution](geodel/README.md#license-and-resources).
