from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path

import pytest

from geodel.config import DEFAULT_CONFIG, PluginConfig


@pytest.fixture
def payload():
    return json.loads(Path(__file__).with_name("fixtures").joinpath("plugin_metadata.json").read_text())["qgisPlugin"]


def test_metadata_defaults_and_immutable_snapshot(payload):
    config = PluginConfig.from_metadata(payload)
    assert config == DEFAULT_CONFIG
    payload["allowedExtensions"].clear()
    payload["retryDelaysSeconds"].append(30)
    assert config.allowed_extensions == (".zip", ".geojson", ".json")
    assert config.retry_delays_seconds == (1, 3, 5)
    with pytest.raises(FrozenInstanceError):
        config.max_file_size_bytes = 1


@pytest.mark.parametrize("updates", [
    {"schemaVersion": 2}, {"schemaVersion": True},
    {"maxFileSizeBytes": 0}, {"maxFileSizeBytes": True}, {"maxFileSizeBytes": "300"},
    {"maxFileSizeBytes": 2**53}, {"maxProjectLayers": -1}, {"maxFilenameLength": 0},
    {"partSizeBytes": 5 * 1024**2 - 1}, {"partSizeBytes": 64 * 1024**2 + 1},
    {"partConcurrency": 9}, {"partSizeBytes": 64 * 1024**2, "partConcurrency": 5},
    {"singlePutThresholdBytes": 5 * 1024**3 + 1}, {"singlePutThresholdBytes": 1},
    {"maxFileSizeBytes": 10 * 1024**2 * 10_000 + 1},
    {"allowedExtensions": []}, {"allowedExtensions": ["zip"]},
    {"allowedExtensions": [".ZIP"]}, {"allowedExtensions": ["../zip"]},
    {"retryDelaysSeconds": [True]}, {"retryDelaysSeconds": [-1]},
    {"retryDelaysSeconds": [31]}, {"retryDelaysSeconds": [1] * 6},
    {"requestTimeoutSeconds": 61}, {"uploadPartTimeoutSeconds": 3601},
    {"processingTimeoutSeconds": 7201}, {"recentUploadsRefreshSeconds": 301},
    {"connectionFeedbackTimeoutSeconds": 61},
])
def test_rejects_invalid_metadata_atomically(payload, updates):
    payload.update(updates)
    with pytest.raises(ValueError):
        PluginConfig.from_metadata(payload)


@pytest.mark.parametrize("invalid", [None, [], "invalid"])
def test_configuration_must_be_an_object(invalid):
    with pytest.raises(ValueError):
        PluginConfig.from_metadata(invalid)


def test_missing_fields_are_rejected(payload):
    del payload["maxFileSizeBytes"]
    with pytest.raises(ValueError, match="maxFileSizeBytes"):
        PluginConfig.from_metadata(payload)


def test_future_extensions_do_not_add_unimplemented_handlers(payload):
    payload.update(allowedExtensions=[".tif", ".json", ".json"], futureSetting=True)
    assert PluginConfig.from_metadata(payload).allowed_extensions == (".json",)
    payload["allowedExtensions"] = [".tif"]
    assert PluginConfig.from_metadata(payload).allowed_extensions == ()


def test_lowering_the_cap_does_not_require_changing_transfer_tuning(payload):
    payload["maxFileSizeBytes"] = 50 * 1024**2
    config = PluginConfig.from_metadata(payload)
    assert config.file_size_label == "50 MiB"
    assert config.single_put_threshold_bytes == DEFAULT_CONFIG.single_put_threshold_bytes


@pytest.mark.parametrize("size, label", [
    (1024, "1,024 bytes"),
    (1024**2, "1 MiB"),
    (200 * 1024**2, "200 MiB"),
    (200 * 1024**2 + 1, "209,715,201 bytes"),
    (200 * 1024**2 + 1024, "209,716,224 bytes"),
    (200_000_000, "200,000,000 bytes"),
])
def test_file_size_label_preserves_exact_metadata_limit(payload, size, label):
    payload["maxFileSizeBytes"] = size
    assert PluginConfig.from_metadata(payload).file_size_label == label


def test_filename_length_matches_backend_for_non_bmp_characters():
    config = replace(DEFAULT_CONFIG, max_filename_length=10)
    config.validate_filename("📍.geojson")
    with pytest.raises(ValueError, match="10 characters"):
        config.validate_filename("📍📍.geojson")
