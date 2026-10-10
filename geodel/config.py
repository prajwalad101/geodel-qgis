from dataclasses import dataclass
from typing import Final


PRODUCT_NAME: Final[str] = "GeoDel"
API_URL: Final[str] = "https://api.geodel.app"
WEB_URL: Final[str] = "https://geodel.app"

SUPPORTED_EXTENSIONS = (".zip", ".geojson", ".json")


@dataclass(frozen=True)
class PluginConfig:
    max_file_size_bytes: int = 200 * 1024**2
    max_project_layers: int = 20
    max_filename_length: int = 255
    allowed_extensions: tuple[str, ...] = SUPPORTED_EXTENSIONS
    single_put_threshold_bytes: int = 100 * 1024**2
    part_size_bytes: int = 10 * 1024**2
    part_concurrency: int = 3
    retry_delays_seconds: tuple[int, ...] = (1, 3, 5)
    request_timeout_seconds: int = 15
    upload_part_timeout_seconds: int = 300
    processing_timeout_seconds: int = 600
    recent_uploads_refresh_seconds: int = 5
    connection_feedback_timeout_seconds: int = 5

    @property
    def file_size_label(self):
        return f"{self.max_file_size_bytes / 1024**2:g} MiB"

    @property
    def extensions_label(self):
        return ", ".join(self.allowed_extensions) or "No supported formats"

    def validate_filename(self, filename):
        if not filename or "/" in filename or "\\" in filename:
            raise ValueError("Upload name cannot be empty or contain slashes.")
        # Match the backend's JavaScript string length for non-BMP characters.
        if len(filename.encode("utf-16-le")) // 2 > self.max_filename_length:
            raise ValueError(f"Upload name must be {self.max_filename_length} characters or fewer.")
        if not filename.lower().endswith(self.allowed_extensions):
            raise ValueError(f"Supported upload formats are {self.extensions_label}.")

    @classmethod
    def from_metadata(cls, payload):
        if (
            not isinstance(payload, dict)
            or type(payload.get("schemaVersion")) is not int
            or payload["schemaVersion"] != 1
        ):
            raise ValueError("Unsupported plugin configuration schema")

        def integer(name, minimum=1, maximum=2**53 - 1):
            value = payload.get(name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"Invalid plugin configuration: {name}")
            return value

        extensions = payload.get("allowedExtensions")
        if not isinstance(extensions, list) or not extensions or not all(
            isinstance(extension, str) and extension.startswith(".")
            and extension == extension.lower() and extension[1:].isalnum()
            for extension in extensions
        ):
            raise ValueError("Invalid plugin configuration: allowedExtensions")
        delays = payload.get("retryDelaysSeconds")
        if not isinstance(delays, list) or len(delays) > 5 or not all(
            type(delay) is int and 0 <= delay <= 30 for delay in delays
        ):
            raise ValueError("Invalid plugin configuration: retryDelaysSeconds")
        config = cls(
            max_file_size_bytes=integer("maxFileSizeBytes"),
            max_project_layers=integer("maxProjectLayers", maximum=10_000),
            max_filename_length=integer("maxFilenameLength", maximum=10_000),
            allowed_extensions=tuple(extension for extension in SUPPORTED_EXTENSIONS if extension in extensions),
            single_put_threshold_bytes=integer("singlePutThresholdBytes", maximum=5 * 1024**3),
            part_size_bytes=integer("partSizeBytes", 5 * 1024**2, 64 * 1024**2),
            part_concurrency=integer("partConcurrency", maximum=8),
            retry_delays_seconds=tuple(delays),
            request_timeout_seconds=integer("requestTimeoutSeconds", maximum=60),
            upload_part_timeout_seconds=integer("uploadPartTimeoutSeconds", maximum=3600),
            processing_timeout_seconds=integer("processingTimeoutSeconds", maximum=7200),
            recent_uploads_refresh_seconds=integer("recentUploadsRefreshSeconds", maximum=300),
            connection_feedback_timeout_seconds=integer("connectionFeedbackTimeoutSeconds", maximum=60),
        )
        if (
            config.part_size_bytes * config.part_concurrency > 256 * 1024**2
            or config.single_put_threshold_bytes < config.part_size_bytes
            or config.max_file_size_bytes > config.part_size_bytes * 10_000
        ):
            raise ValueError("Invalid plugin configuration: multipart limits")
        return config


DEFAULT_CONFIG = PluginConfig()
