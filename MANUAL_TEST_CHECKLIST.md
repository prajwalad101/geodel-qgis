# GeoDel QGIS plugin manual test checklist

Run every check on QGIS 3.44 LTR and the latest stable QGIS release before
publishing a plugin version.

This standalone snapshot has not completed these runtime checks. Record new
results below before any release; earlier development checks are not release evidence.

## Checklist

### Install and first connection

- [ ] Install `dist/geodel.zip` through Plugin Manager without errors; the
  ```
  GeoDel toolbar icon appears and toggles the panel.
  ```
- [ ] With no key saved, confirm the panel shows only connection controls, shows
  ```
  **GeoDel isn’t connected**, explains what is unavailable, and exposes
  **Open API Key Setup**, a masked Personal API Key field, and **Save and
  connect** (disabled until a key is pasted).
  ```
- [ ] Confirm **Open API Key Setup** opens `/qgis/setup` in the default browser.
- [ ] Paste a valid key and choose **Save and connect**; confirm QGIS asks for
  ```
  (or to set) its master password, workspaces load, and operational
  controls appear with **Connected to GeoDel** and **Connection
  management**.
  ```
- [ ] Restart QGIS; confirm the connection, workspace, and folders return
  ```
  without re-entering the key, and the key is absent from `QgsSettings`.
  ```

### Connection errors

- [ ] Paste an invalid key; confirm setup stays open with "This API key isn't
  ```
  valid…" and operational controls stay hidden.
  ```
- [ ] Delete the saved key on the web, then reopen the panel; confirm it returns
  ```
  to setup with "Your saved API key is no longer valid…" and the key field
  is enabled.
  ```
- [ ] Stop the API before first connection; confirm "Couldn't connect to
  ```
  server. If this keeps happening please contact support." appears within
  about 5 seconds with a **Refresh** button, and the key field is enabled.
  ```
- [ ] Start the API and choose **Refresh**; confirm it connects.
- [ ] Stop the API while connected and choose **Refresh** on the upload screen;
  ```
  confirm the upload screen stays with "Connection preserved…".
  ```
- [ ] Use a valid key for a User with no Workspace; confirm Workspace
  ```
  setup guidance, **Set up a Workspace**, and **Refresh** appear.
  ```

### Connection management

- [ ] Choose **Connection management**; confirm **Back to uploads** returns to
  ```
  the upload screen and **Refresh** validates the saved key.
  ```
- [ ] Paste an invalid replacement key; confirm the error shows and \*\*Back to
  ```
  uploads** still works with the old connection.
  ```
- [ ] Paste a valid replacement key; confirm it is saved and used.

### Workspaces and folders

- [ ] On first load, confirm the folder picker lists the selected
  ```
  workspace's folders (not only **Files (root)**) without switching
  workspaces.
  ```
- [ ] Switch workspace; confirm folders and recent uploads reload for it.
- [ ] Choose a folder, close and reopen the panel; confirm workspace and
  ```
  folder choices persist.
  ```

### Uploads

- [ ] Upload one vector layer; confirm EPSG:4326 GeoJSON export, task progress,
  ```
  ready notification, and **Copy share link** works.
  ```
- [ ] Upload multiple vector layers; confirm one zipped Shapefile upload.
- [ ] Confirm raster layers are not listed.
- [ ] Browse and upload a `.geojson`, `.json`, or `.zip` file; confirm it
  ```
  uploads unchanged and other file types are rejected.
  ```
- [ ] Confirm an empty layer, more than 20 layers, a file over 60 MB, and an
  ```
  upload name containing `/` fail before transfer with a clear message.
  ```
- [ ] Confirm the upload lands in the chosen folder (or root) on the web.

### Recent uploads

- [ ] Keep the panel open during processing; confirm status updates without
  ```
  manual refresh.
  ```
- [ ] Confirm ready rows copy share links and open upload details in browser.
- [ ] Confirm failed uploads render red with a short reason and a working web
  ```
  link.
  ```
- [ ] Confirm partial success shows ⚠ with a tooltip naming failed layers.
- [ ] Confirm health warnings show "⚠ N health warning(s)" on one line.

### Version

- [ ] Raise server `minPluginVersion` above the installed version; confirm the
  ```
  "Please update the GeoDel plugin to continue." notice and message bar
  warning appear.
  ```

## Execution record

| Version | QGIS version  | OS  | Tester | Date | Result  | Notes |
| ------- | ------------- | --- | ------ | ---- | ------- | ----- |
|         | 3.44 LTR      |     |        |      | Not run |       |
|         | Latest stable |     |        |      | Not run |       |

QGIS Plugin Repository URL after submission: _Not submitted_
