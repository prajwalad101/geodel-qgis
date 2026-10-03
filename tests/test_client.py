from unittest.mock import Mock, patch

import pytest
import requests

from geodel.client import (
    MAX_FILE_SIZE,
    PART_SIZE,
    AuthenticationError,
    AuthorizationError,
    GeoDelClient,
    GeoDelError,
    ServerUnavailableError,
    UploadCanceled,
)


def response(status_code, payload, headers=None):
    result = Mock(status_code=status_code, headers=headers or {})
    result.json.return_value = payload
    if status_code >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} Server Error"
        )
    return result


def test_lists_organizations_with_plugin_auth_headers():
    session = Mock()
    session.request.return_value = response(
        200,
        {"organizations": [{"id": "org-1", "name": "Field Team"}]},
    )
    client = GeoDelClient(
        "https://example.com/",
        "geodel_secret",
        "0.1.0",
        session=session,
    )

    assert client.list_organizations() == [{"id": "org-1", "name": "Field Team"}]
    session.request.assert_called_once_with(
        "GET",
        "https://example.com/api/v1/organizations",
        headers={
            "Authorization": "Bearer geodel_secret",
            "X-Plugin-Version": "0.1.0",
        },
        timeout=15,
    )


def test_revoked_key_raises_clear_authentication_error():
    session = Mock()
    session.request.return_value = response(401, {"message": "Unauthorized"})
    client = GeoDelClient(
        "https://example.com",
        "geodel_revoked",
        "0.1.0",
        session=session,
    )

    with pytest.raises(AuthenticationError, match="API key is invalid or revoked"):
        client.list_organizations()


def test_forbidden_response_is_not_reported_as_revoked_key():
    session = Mock()
    session.request.return_value = response(403, {"message": "Forbidden"})
    client = GeoDelClient(
        "https://example.com",
        "geodel_valid",
        "0.1.0",
        session=session,
    )

    with pytest.raises(AuthorizationError, match="does not have access"):
        client.list_organizations()


def test_server_error_uses_http_failure():
    session = Mock()
    session.request.return_value = response(500, {"message": "Server error"})
    client = GeoDelClient(
        "https://example.com",
        "geodel_valid",
        "0.1.0",
        session=session,
    )

    with pytest.raises(GeoDelError) as caught:
        client.list_organizations()

    assert str(caught.value) == "GeoDel request failed: Server error"


def test_api_errors_use_configured_product_name(monkeypatch):
    monkeypatch.setattr("geodel.client.PRODUCT_NAME", "Maply")
    session = Mock()
    session.request.return_value = response(500, {"message": "Server error"})
    client = GeoDelClient(
        "https://example.com",
        "geodel_valid",
        "0.1.0",
        session=session,
    )

    with pytest.raises(GeoDelError, match="Maply request failed: Server error"):
        client.list_organizations()


@pytest.mark.parametrize(
    ("minimum", "requires_update"),
    [("0.1.0", False), ("0.2.0", True), ("0.1.1", True)],
)
def test_meta_version_gate(minimum, requires_update):
    session = Mock()
    session.request.return_value = response(
        200, {"minPluginVersion": minimum, "pluginVersion": "0.1.0"}
    )
    client = GeoDelClient(
        "https://example.com",
        "",
        "0.1.0",
        session=session,
    )

    assert client.requires_update() is requires_update
    assert "Authorization" not in session.request.call_args.kwargs["headers"]


@pytest.mark.parametrize(
    ("plugin_version", "minimum", "message"),
    [
        ("invalid", "0.1.0", "Installed plugin version is invalid"),
        ("0.1.0", "invalid", "minimum plugin version"),
    ],
)
def test_version_gate_identifies_invalid_version_source(
    plugin_version, minimum, message
):
    session = Mock()
    session.request.return_value = response(200, {"minPluginVersion": minimum})
    client = GeoDelClient(
        "https://example.com",
        "",
        plugin_version,
        session=session,
    )

    with pytest.raises(GeoDelError, match=message):
        client.requires_update()


def test_lists_folders_for_selected_organization():
    session = Mock()
    session.request.return_value = response(
        200,
        {
            "folders": [
                {
                    "id": "folder-1",
                    "name": "Projects",
                }
            ]
        },
    )
    client = GeoDelClient(
        "https://example.com",
        "geodel_secret",
        "0.1.0",
        session=session,
    )

    assert client.list_folders("org-1")[0]["name"] == "Projects"
    assert session.request.call_args.kwargs["headers"]["X-Organization-Id"] == "org-1"


@pytest.mark.parametrize("folder", [
    None,
    {},
    {"id": 1, "name": "Projects"},
    {"id": "folder-1", "name": 1},
])
def test_rejects_invalid_folders(folder):
    session = Mock()
    session.request.return_value = response(200, {"folders": [folder]})
    client = GeoDelClient("https://example.com", "key", "0.1.0", session=session)
    with pytest.raises(GeoDelError, match="invalid folders response"):
        client.list_folders("org-1")


def test_lists_recent_uploads_with_owner_summary():
    uploads = [
        {
            "id": "upload-1",
            "originalFilename": "roads.zip",
            "status": "ready",
            "shareToken": "share-1",
            "errorMessage": None,
            "layerSummary": {
                "total": 2,
                "ready": 1,
                "failed": 1,
                "warningCount": 2,
                "failedLayers": [
                    {"name": "water", "reason": "Could not read geometry"}
                ],
            },
        }
    ]
    session = Mock()
    session.request.return_value = response(200, {"uploads": uploads})
    client = GeoDelClient(
        "https://example.com",
        "geodel_secret",
        "0.1.0",
        session=session,
    )

    projected = client.list_recent_uploads("org-1")[0]
    assert projected.filename == "roads.zip"
    assert projected.failed_layers_tooltip == "water: Could not read geometry"
    assert projected.health_warning_label == "⚠ 2 health warnings"
    assert projected.copy_share_url == "https://example.com/s/share-1"
    assert session.request.call_args.kwargs["headers"]["X-Organization-Id"] == "org-1"
    assert session.request.call_args.kwargs["params"] == {"recent": "true"}


def test_multipart_upload_sends_original_bytes_and_reports_progress(tmp_path):
    source = tmp_path / "roads.geojson"
    original = b"a" * PART_SIZE + b"last byte"
    source.write_bytes(original)
    session = Mock()
    session.request.side_effect = [
        response(
            200,
            {"attemptId": "attempt-1", "key": "attempt-1", "uploadId": "attempt-1"},
        ),
        response(200, {"url": "https://storage.example.com/part-1"}),
        response(200, None, {"ETag": '"etag-1"'}),
        response(200, {"url": "https://storage.example.com/part-2"}),
        response(200, None, {"ETag": '"etag-2"'}),
        response(200, {"key": "attempt-1"}),
        response(200, {"id": "upload-1"}),
    ]
    progress = []
    client = GeoDelClient(
        "https://example.com",
        "geodel_secret",
        "0.1.0",
        session=session,
    )

    upload_id = client.upload_file(
        source,
        "Client roads.geojson",
        "org-1",
        "folder-1",
        progress.append,
    )

    assert upload_id == "upload-1"
    assert session.request.call_args_list[2].args == (
        "PUT",
        "https://storage.example.com/part-1",
    )
    uploaded = (
        session.request.call_args_list[2].kwargs["data"]
        + session.request.call_args_list[4].kwargs["data"]
    )
    assert uploaded == original
    assert session.request.call_args_list[6].kwargs["json"] == {
        "attemptId": "attempt-1",
        "folderId": "folder-1",
    }
    assert len(progress) == 2
    assert progress[-1] == 100.0


def test_reads_upload_status_and_share_token():
    session = Mock()
    session.request.side_effect = [
        response(
            200,
            {
                "id": "upload-1",
                "status": "processing",
                "errorMessage": None,
            },
        ),
        response(200, {"shareToken": "share-1"}),
    ]
    client = GeoDelClient(
        "https://example.com",
        "geodel_secret",
        "0.1.0",
        session=session,
    )

    assert client.get_upload_status("upload-1", "org-1") == {
        "id": "upload-1",
        "status": "processing",
        "errorMessage": None,
    }
    assert client.get_share_token("upload-1", "org-1") == "share-1"


def test_publishes_file_until_share_link_is_ready(tmp_path):
    source = tmp_path / "roads.geojson"
    source.write_text("{}")
    client = GeoDelClient(
        "https://example.com",
        "geodel_secret",
        "0.1.0",
        session=Mock(),
    )
    client.upload_file = Mock(
        side_effect=lambda *args: (args[4](50), "upload-1")[1]
    )
    client.get_upload_status = Mock(
        return_value={
            "id": "upload-1",
            "status": "ready",
            "errorMessage": None,
        }
    )
    client.get_share_token = Mock(return_value="share-1")
    progress = []

    result = client.publish_file(
        source,
        "roads.geojson",
        "org-1",
        progress=progress.append,
    )

    assert result == {"shareToken": "share-1", "timedOut": False}
    assert progress == [45, 100]


def test_publish_retries_transient_status_and_share_link_errors(tmp_path):
    source = tmp_path / "roads.geojson"
    source.write_text("{}")
    client = GeoDelClient(
        "https://example.com",
        "geodel_secret",
        "0.1.0",
        session=Mock(),
    )
    client.upload_file = Mock(return_value="upload-1")
    processing = {
        "id": "upload-1",
        "status": "processing",
        "errorMessage": None,
    }
    ready = {"id": "upload-1", "status": "ready", "errorMessage": None}
    client.get_upload_status = Mock(
        side_effect=[GeoDelError("temporary"), processing, ready, ready]
    )
    client.get_share_token = Mock(
        side_effect=[GeoDelError("temporary"), "share-1"]
    )
    now = [0.0]

    with patch("geodel.client.monotonic", side_effect=lambda: now[0]), patch(
        "geodel.client.sleep",
        side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds),
    ):
        result = client.publish_file(source, "roads.geojson", "org-1")

    assert result == {"shareToken": "share-1", "timedOut": False}
    assert client.get_upload_status.call_count == 4
    assert client.get_share_token.call_count == 2


def test_publish_cancels_while_waiting_for_processing(tmp_path):
    source = tmp_path / "roads.geojson"
    source.write_text("{}")
    client = GeoDelClient(
        "https://example.com",
        "geodel_secret",
        "0.1.0",
        session=Mock(),
    )
    client.upload_file = Mock(return_value="upload-1")
    client.get_upload_status = Mock(
        return_value={
            "id": "upload-1",
            "status": "processing",
            "errorMessage": None,
        }
    )

    with pytest.raises(UploadCanceled, match="Upload canceled"):
        client.publish_file(
            source,
            "roads.geojson",
            "org-1",
            is_canceled=Mock(side_effect=[False, True]),
        )


def test_publish_returns_timeout_outcome(tmp_path):
    source = tmp_path / "roads.geojson"
    source.write_text("{}")
    client = GeoDelClient(
        "https://example.com",
        "geodel_secret",
        "0.1.0",
        session=Mock(),
    )
    client.upload_file = Mock(return_value="upload-1")
    client.get_upload_status = Mock(
        return_value={
            "id": "upload-1",
            "status": "processing",
            "errorMessage": None,
        }
    )
    now = [0.0]

    with patch("geodel.client.POLL_TIMEOUT_SECONDS", 1), patch(
        "geodel.client.monotonic", side_effect=lambda: now[0]
    ), patch(
        "geodel.client.sleep",
        side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds),
    ):
        result = client.publish_file(source, "roads.geojson", "org-1")

    assert result == {"timedOut": True}


def test_rejects_file_over_max_size_before_request(tmp_path):
    source = tmp_path / "too-large.zip"
    with source.open("wb") as file:
        file.truncate(MAX_FILE_SIZE + 1)
    session = Mock()
    client = GeoDelClient(
        "https://example.com",
        "geodel_secret",
        "0.1.0",
        session=session,
    )

    with pytest.raises(GeoDelError, match="60 MB"):
        client.upload_file(source, "too-large.zip", "org-1")

    session.request.assert_not_called()


def test_unreachable_server_raises_server_unavailable_error():
    session = Mock()
    session.request.side_effect = requests.ConnectionError("DNS failure")
    client = GeoDelClient(
        "https://example.com", "geodel_secret", "0.1.0", session=session
    )

    with pytest.raises(ServerUnavailableError):
        client.list_organizations()


def test_server_error_raises_server_unavailable_error():
    session = Mock()
    session.request.return_value = response(503, {"message": "Unavailable"})
    client = GeoDelClient(
        "https://example.com", "geodel_secret", "0.1.0", session=session
    )

    with pytest.raises(ServerUnavailableError):
        client.list_organizations()


def test_rejected_key_is_not_server_unavailable():
    session = Mock()
    session.request.return_value = response(401, {"message": "Unauthorized"})
    client = GeoDelClient("https://example.com", "geodel_bad", "0.1.0", session=session)

    with pytest.raises(AuthenticationError) as error:
        client.list_organizations()
    assert not isinstance(error.value, ServerUnavailableError)
