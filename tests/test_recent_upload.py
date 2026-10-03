import pytest

from geodel.recent_upload import project_recent_upload


def test_projects_partial_success_into_render_ready_facts():
    upload = {
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
                {
                    "name": "water",
                    "reason": "Could not read geometry\ninternal detail",
                }
            ],
        },
    }

    projected = project_recent_upload(upload, "https://example.com/api/v1")

    assert projected.filename == "roads.zip"
    assert projected.status_label == "Ready"
    assert projected.is_failed is False
    assert projected.failed_layers_tooltip == "water: Could not read geometry"
    assert projected.error_reason is None
    assert projected.health_warning_label == "⚠ 2 health warnings"
    assert projected.copy_share_url == "https://example.com/s/share-1"
    assert projected.details_url == "https://example.com/upload-1"
    assert projected.details_label == "Open in web"


def test_rejects_uploads_with_inconsistent_layer_outcomes():
    invalid_outcomes = (
        ("ready", 1, 0, 1, [{"name": "roads", "reason": "invalid"}]),
        ("failed", 1, 1, 0, []),
        ("ready", 2, 1, 0, []),
        ("ready", 2, 1, 1, []),
    )
    for status, total, ready, failed, failed_layers in invalid_outcomes:
        upload = {
            "id": "upload-1",
            "originalFilename": "roads.zip",
            "status": status,
            "shareToken": "share-1",
            "errorMessage": None,
            "layerSummary": {
                "total": total,
                "ready": ready,
                "failed": failed,
                "warningCount": 0,
                "failedLayers": failed_layers,
            },
        }

        with pytest.raises(ValueError, match="invalid Upload"):
            project_recent_upload(upload, "https://example.com/api/v1")
