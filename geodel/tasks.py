"""Background workers; keep widgets and controller state on the GUI thread."""
from pathlib import Path

from .client import GeoDelClient, UploadCanceled
from .metadata import PLUGIN_VERSION
from .qgis_transport import QgisTransport


def _client(task, server_url, api_key=""):
    return GeoDelClient(
        server_url, api_key, PLUGIN_VERSION, QgisTransport(), task.isCanceled
    )


def _load_organizations(task, server_url, api_key):
    if task.isCanceled():
        return None
    organizations = _client(task, server_url, api_key).list_organizations()
    return None if task.isCanceled() else organizations


def _requires_update(task, server_url):
    if task.isCanceled():
        return None
    requires_update = _client(task, server_url).requires_update()
    return None if task.isCanceled() else requires_update


def _load_folders(task, server_url, api_key, organization_id):
    if task.isCanceled():
        return None
    folders = _client(task, server_url, api_key).list_folders(
        organization_id
    )
    return None if task.isCanceled() else folders


def _load_recent_uploads(task, server_url, api_key, organization_id):
    if task.isCanceled():
        return None
    uploads = _client(task, server_url, api_key).list_recent_uploads(
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
):
    path = artifact.path if artifact else Path(path)
    client = _client(task, server_url, api_key)
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
