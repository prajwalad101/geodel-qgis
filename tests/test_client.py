from unittest.mock import MagicMock, Mock, patch

import pytest
import json
from geodel.transport import Response, Transport, TransportError

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


@pytest.fixture(autouse=True)
def multipart_policy(monkeypatch):
    # These legacy cases exercise multipart cleanup; single PUT has its own tests.
    monkeypatch.setattr("geodel.client.SINGLE_PUT_THRESHOLD", 0)


def response(status_code, payload, headers=None):
    return Response(status_code, json.dumps(payload).encode(), headers or {})


def test_lists_organizations_with_plugin_auth_headers():
    transport = MagicMock(spec=Transport)
    transport.request.return_value = response(
        200,
        {"organizations": [{"id": "org-1", "name": "Field Team"}]},
    )
    client = GeoDelClient(
        "https://example.com/",
        "geodel_secret",
        "0.1.0",
        transport=transport,
    )

    assert client.list_organizations() == [{"id": "org-1", "name": "Field Team"}]
    transport.request.assert_called_once_with(
        "GET",
        "https://example.com/api/v1/organizations",
        headers={
            "Authorization": "Bearer geodel_secret",
            "X-Plugin-Version": "0.1.0",
        },
        timeout=15,
        is_canceled=None,
    )


def test_unauthorized_response_reports_authentication_failure_without_guessing_cause():
    transport = MagicMock(spec=Transport)
    transport.request.return_value = response(401, {"message": "Unauthorized"})
    client = GeoDelClient(
        "https://example.com",
        "geodel_revoked",
        "0.1.0",
        transport=transport,
    )

    with pytest.raises(AuthenticationError, match="Authentication failed") as caught:
        client.list_organizations()
    assert "API key" not in str(caught.value)


def test_forbidden_response_is_not_reported_as_revoked_key():
    transport = MagicMock(spec=Transport)
    transport.request.return_value = response(403, {"message": "Forbidden"})
    client = GeoDelClient(
        "https://example.com",
        "geodel_valid",
        "0.1.0",
        transport=transport,
    )

    with pytest.raises(AuthorizationError, match="Request denied") as caught:
        client.list_organizations()
    assert "API key" not in str(caught.value)


@pytest.mark.parametrize("payload", [
    {"message": "Forbidden"},
    {"reason": "unknown_reason"},
    {"message": "Trial expired"},
    {},
    None,
])
def test_generic_forbidden_response_does_not_guess_why_request_was_denied(payload):
    transport = MagicMock(spec=Transport)
    transport.request.return_value = response(403, payload)
    client = GeoDelClient("https://example.com", "key", "0.1.0", transport=transport)

    with pytest.raises(AuthorizationError) as caught:
        client.list_recent_uploads("org-1")

    assert str(caught.value) == "Request denied by GeoDel (HTTP 403)."


@pytest.mark.parametrize(("reason", "message"), [
    ("trial_expired", "Your workspace trial has expired."),
    ("capacity_exhausted", "This upload would exceed your workspace storage capacity."),
    ("subscription_on_hold", "Your workspace subscription is on hold."),
    ("subscription_required", "Your workspace needs a subscription to upload files."),
])
def test_explicit_workspace_restriction_reason_reports_known_cause(reason, message):
    transport = MagicMock(spec=Transport)
    transport.request.return_value = response(403, {"reason": reason})
    client = GeoDelClient("https://example.com", "key", "0.1.0", transport=transport)

    with pytest.raises(AuthorizationError) as caught:
        client.list_recent_uploads("org-1")
    assert str(caught.value).startswith(message)


def test_server_error_uses_http_failure():
    transport = MagicMock(spec=Transport)
    transport.request.return_value = response(500, {"message": "Server error"})
    client = GeoDelClient(
        "https://example.com",
        "geodel_valid",
        "0.1.0",
        transport=transport,
    )

    with pytest.raises(GeoDelError) as caught:
        client.list_organizations()

    assert str(caught.value) == "GeoDel server error (HTTP 500). Try again later."


def test_api_errors_use_configured_product_name(monkeypatch):
    monkeypatch.setattr("geodel.client.PRODUCT_NAME", "Maply")
    transport = MagicMock(spec=Transport)
    transport.request.return_value = response(500, {"message": "Server error"})
    client = GeoDelClient(
        "https://example.com",
        "geodel_valid",
        "0.1.0",
        transport=transport,
    )

    with pytest.raises(GeoDelError, match="Maply server error"):
        client.list_organizations()


@pytest.mark.parametrize(("status", "payload", "message"), [
    (400, {"error": "Invalid request"}, "GeoDel rejected the request as invalid."),
    (400, {"error": "X-Organization-Id header is required for API key requests"}, "No workspace was sent with this request."),
    (400, {"error": "uploaded object size is unavailable"}, "GeoDel could not verify the uploaded file size."),
    (400, {"message": "uploaded object size does not match request"}, "The uploaded file size does not match the submitted size."),
    (400, {"error": "Multipart upload reference is invalid"}, "The upload reference is invalid."),
    (403, {"error": "Upload attempt does not belong to the current session"}, "This upload attempt belongs to a different account or workspace."),
    (404, {"error": "Upload attempt not found"}, "The upload attempt was not found."),
    (404, {"error": "Upload not found"}, "The upload was not found."),
    (404, {"error": "Folder not found"}, "The selected folder was not found."),
    (404, {"error": "Organization not found"}, "The selected workspace was not found."),
    (413, {}, "The upload request exceeds the server's size limit."),
    (429, {}, "Too many requests to GeoDel."),
    (503, {"error": "Internal Server Error"}, "GeoDel server error (HTTP 503)."),
    (400, {"error": "unknown detail"}, "GeoDel request failed (HTTP 400)."),
    (404, {}, "GeoDel request failed (HTTP 404)."),
    (403, {"reason": []}, "Request denied by GeoDel (HTTP 403)."),
    (403, {"reason": "trial_expired", "error": "Forbidden"}, "Your workspace trial has expired."),
    # Known words with an unrelated status must not imply a specific cause.
    (500, {"error": "Folder not found"}, "GeoDel server error (HTTP 500)."),
    (400, {"reason": "trial_expired"}, "GeoDel request failed (HTTP 400)."),
])
def test_http_failure_messages_use_only_identified_server_causes(status, payload, message):
    transport = MagicMock(spec=Transport)
    transport.request.return_value = response(status, payload)
    client = GeoDelClient("https://example.com", "key", "0.1.0", transport=transport)

    with pytest.raises(GeoDelError) as caught:
        client.list_recent_uploads("org-1")

    assert str(caught.value).startswith(message)
    assert isinstance(caught.value, ServerUnavailableError) is (status >= 500)
    assert isinstance(caught.value, AuthorizationError) is (status == 403)


@pytest.mark.parametrize("status", [400, 403, 500])
def test_http_failure_with_non_json_body_has_generic_message(status):
    transport = MagicMock(spec=Transport)
    transport.request.return_value = Response(status, b"<html>unknown server error</html>")
    client = GeoDelClient("https://example.com", "key", "0.1.0", transport=transport)

    with pytest.raises(GeoDelError) as caught:
        client.list_recent_uploads("org-1")

    assert f"HTTP {status}" in str(caught.value)
    assert "unknown server error" not in str(caught.value)


@pytest.mark.parametrize(
    ("minimum", "requires_update"),
    [("0.1.0", False), ("0.2.0", True), ("0.1.1", True)],
)
def test_meta_version_gate(minimum, requires_update):
    transport = MagicMock(spec=Transport)
    transport.request.return_value = response(
        200, {"minPluginVersion": minimum, "pluginVersion": "0.1.0"}
    )
    client = GeoDelClient(
        "https://example.com",
        "",
        "0.1.0",
        transport=transport,
    )

    assert client.requires_update() is requires_update
    assert "Authorization" not in transport.request.call_args.kwargs["headers"]


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
    transport = MagicMock(spec=Transport)
    transport.request.return_value = response(200, {"minPluginVersion": minimum})
    client = GeoDelClient(
        "https://example.com",
        "",
        plugin_version,
        transport=transport,
    )

    with pytest.raises(GeoDelError, match=message):
        client.requires_update()


def test_lists_folders_for_selected_organization():
    transport = MagicMock(spec=Transport)
    transport.request.return_value = response(
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
        transport=transport,
    )

    assert client.list_folders("org-1")[0]["name"] == "Projects"
    assert transport.request.call_args.kwargs["headers"]["X-Organization-Id"] == "org-1"


@pytest.mark.parametrize("folder", [
    None,
    {},
    {"id": 1, "name": "Projects"},
    {"id": "folder-1", "name": 1},
])
def test_rejects_invalid_folders(folder):
    transport = MagicMock(spec=Transport)
    transport.request.return_value = response(200, {"folders": [folder]})
    client = GeoDelClient("https://example.com", "key", "0.1.0", transport=transport)
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
    transport = MagicMock(spec=Transport)
    transport.request.return_value = response(200, {"uploads": uploads})
    client = GeoDelClient(
        "https://example.com",
        "geodel_secret",
        "0.1.0",
        transport=transport,
    )

    projected = client.list_recent_uploads("org-1")[0]
    assert projected.filename == "roads.zip"
    assert projected.failed_layers_tooltip == "water: Could not read geometry"
    assert projected.health_warning_label == "⚠ 2 health warnings"
    assert projected.copy_share_url == "https://example.com/s/share-1"
    assert transport.request.call_args.kwargs["headers"]["X-Organization-Id"] == "org-1"
    assert transport.request.call_args.kwargs["params"] == {"recent": "true"}


@pytest.mark.parametrize("summary", [{}, [], "invalid"])
def test_recent_uploads_reject_malformed_layer_summary(summary):
    transport = MagicMock(spec=Transport)
    transport.request.return_value = response(200, {"uploads": [{
        "id": "upload-1",
        "originalFilename": "roads.zip",
        "status": "ready",
        "shareToken": "share-1",
        "layerSummary": summary,
    }]})
    client = GeoDelClient("https://example.com", "key", "0.1.0", transport=transport)

    with pytest.raises(GeoDelError, match="invalid uploads response"):
        client.list_recent_uploads("org-1")


def test_recent_uploads_include_failed_upload_with_retained_ready_layer():
    uploads = [
        {
            "id": f"upload-{index}",
            "originalFilename": f"roads-{index}.zip",
            "status": "failed" if index == 2 else "ready",
            "shareToken": f"share-{index}",
            "errorMessage": "Processing failed" if index == 2 else None,
            "layerSummary": {
                "total": 1, "ready": 1, "failed": 0,
                "warningCount": 0, "failedLayers": [],
            },
        }
        for index in range(10)
    ]
    transport = MagicMock(spec=Transport)
    transport.request.return_value = response(200, {"uploads": uploads})
    client = GeoDelClient("https://example.com", "key", "0.1.0", transport=transport)

    projected = client.list_recent_uploads("org-1")

    assert len(projected) == 10
    assert projected[2].status_label == "Failed"
    assert projected[2].is_failed is True
    assert projected[2].error_reason == "Processing failed"
    assert projected[2].copy_share_url is None
    assert projected[2].details_url == "https://example.com/upload-2"
    assert projected[0].copy_share_url == "https://example.com/s/share-0"


def test_multipart_upload_sends_original_bytes_and_reports_progress(tmp_path):
    from test_upload_efficiency import UploadTransport

    source = tmp_path / "roads.geojson"
    original = b"a" * PART_SIZE + b"last byte"
    source.write_bytes(original)
    transport = UploadTransport()
    progress = []
    client = GeoDelClient("https://example.com", "geodel_secret", "0.1.0", transport)
    assert client.upload_file(source, "Client roads.geojson", "org-1", "folder-1", progress.append) == "upload"
    assert transport.parts["/1"] + transport.parts["/2"] == original
    assert transport.calls[-1][2]["json"] == {"attemptId": "attempt", "folderId": "folder-1"}
    assert progress == sorted(progress)
    assert progress[-1] == 100.0


def test_reads_upload_status_and_share_token():
    transport = MagicMock(spec=Transport)
    transport.request.side_effect = [
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
        transport=transport,
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
        transport=MagicMock(spec=Transport),
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
        transport=MagicMock(spec=Transport),
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
        transport=MagicMock(spec=Transport),
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
        transport=MagicMock(spec=Transport),
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
    transport = MagicMock(spec=Transport)
    client = GeoDelClient(
        "https://example.com",
        "geodel_secret",
        "0.1.0",
        transport=transport,
    )

    with pytest.raises(GeoDelError, match="200 MB"):
        client.upload_file(source, "too-large.zip", "org-1")

    transport.request.assert_not_called()


def test_unreachable_server_raises_server_unavailable_error():
    transport = MagicMock(spec=Transport)
    transport.request.side_effect = TransportError("DNS failure")
    client = GeoDelClient(
        "https://example.com", "geodel_secret", "0.1.0", transport=transport
    )

    with pytest.raises(ServerUnavailableError):
        client.list_organizations()


def test_server_error_raises_server_unavailable_error():
    transport = MagicMock(spec=Transport)
    transport.request.return_value = response(503, {"message": "Unavailable"})
    client = GeoDelClient(
        "https://example.com", "geodel_secret", "0.1.0", transport=transport
    )

    with pytest.raises(ServerUnavailableError):
        client.list_organizations()


def test_rejected_key_is_not_server_unavailable():
    transport = MagicMock(spec=Transport)
    transport.request.return_value = response(401, {"message": "Unauthorized"})
    client = GeoDelClient("https://example.com", "geodel_bad", "0.1.0", transport=transport)

    with pytest.raises(AuthenticationError) as error:
        client.list_organizations()
    assert not isinstance(error.value, ServerUnavailableError)
