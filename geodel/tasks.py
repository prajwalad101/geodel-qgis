"""Background workers; keep widgets and controller state on the GUI thread."""
from pathlib import Path

from .client import GeoDelClient, UploadCanceled
from .config import DEFAULT_CONFIG, PluginConfig
from .metadata import PLUGIN_VERSION
from .qgis_transport import QgisTransport


def _client(task, server_url, api_key="", config=DEFAULT_CONFIG):
    return GeoDelClient(
        server_url, api_key, PLUGIN_VERSION, QgisTransport(), task.isCanceled, config
    )


def _load_organizations(task, server_url, api_key, config=DEFAULT_CONFIG):
    if task.isCanceled():
        return None
    organizations = _client(task, server_url, api_key, config).list_organizations()
    return None if task.isCanceled() else organizations


def _load_metadata(task, server_url, config=DEFAULT_CONFIG):
    if task.isCanceled():
        return None
    client = _client(task, server_url, config=config)
    metadata = client.get_meta()
    requires_update = client.requires_update(metadata)
    plugin_config = None
    config_error = False
    if "qgisPlugin" in metadata:
        try:
            plugin_config = PluginConfig.from_metadata(metadata["qgisPlugin"])
        except ValueError:
            config_error = True
    return None if task.isCanceled() else (requires_update, plugin_config, config_error)


def _load_folders(task, server_url, api_key, organization_id, config=DEFAULT_CONFIG):
    if task.isCanceled():
        return None
    folders = _client(task, server_url, api_key, config).list_folders(
        organization_id
    )
    return None if task.isCanceled() else folders


def _load_recent_uploads(task, server_url, api_key, organization_id, config=DEFAULT_CONFIG):
    if task.isCanceled():
        return None
    uploads = _client(task, server_url, api_key, config).list_recent_uploads(
        organization_id
    )
    return None if task.isCanceled() else uploads


def _upload_file(
    task,
    server_url,
    api_key,
    organization_id,
    folder_id,
    path,
    upload_filename,
    artifact=None,
    config=DEFAULT_CONFIG,
):
    path = artifact.path if artifact else Path(path)
    client = _client(task, server_url, api_key, config)
    try:
        # Stop once bytes are sent; Recent uploads polls processing -> ready.
        return client.upload_file(
            path,
            upload_filename,
            organization_id,
            folder_id,
            task.setProgress,
            task.isCanceled,
        )
    except UploadCanceled:
        return None
    finally:
        if artifact:
            artifact.cleanup()
