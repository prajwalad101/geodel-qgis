"""Client behavior at the injected HTTP boundary, without QGIS imports."""
import json

from geodel.client import GeoDelClient


class FixtureTransport:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_client_uses_injected_transport_with_auth_and_tenancy():
    from geodel.transport import Response

    transport = FixtureTransport(Response(200, json.dumps({"folders": []}).encode()))
    client = GeoDelClient("https://example.com", "synthetic-key", "0.1.0", transport)
    assert client.list_folders("workspace-1") == []
    method, url, options = transport.calls[0]
    assert (method, url) == ("GET", "https://example.com/api/v1/folders")
    assert options["headers"] == {
        "Authorization": "Bearer synthetic-key",
        "X-Plugin-Version": "0.1.0",
        "X-Organization-Id": "workspace-1",
    }
    assert options["timeout"] == 15


def test_canceled_part_attempts_cleanup_without_canceled_feedback(tmp_path):
    import pytest
    from geodel.client import UploadCanceled
    from geodel.transport import Response, TransportCanceled

    class CancelDuringPart(FixtureTransport):
        def request(self, method, url, **options):
            if method == "PUT":
                assert options["is_canceled"] is canceled
                raise TransportCanceled("canceled")
            if method == "DELETE":
                assert not options["is_canceled"]()
                assert options["timeout"] == 15
            return super().request(method, url, **options)

    canceled = lambda: False
    transport = CancelDuringPart(
        Response(200, b'{"uploadId":"attempt-1","key":"storage-key"}'),
        Response(200, b'{"url":"https://storage.example.com/part"}'),
        Response(200, b'{}'),
    )
    source = tmp_path / "roads.geojson"
    source.write_bytes(b'{}')
    client = GeoDelClient("https://example.com", "synthetic-key", "0.1.0", transport)
    with pytest.raises(UploadCanceled):
        client.upload_file(source, source.name, "workspace-1", is_canceled=canceled)
    assert transport.calls[-1][0] == "DELETE"


def test_multipart_registration_failure_attempts_cleanup(tmp_path):
    import pytest
    from geodel.client import GeoDelError
    from geodel.transport import Response

    transport = FixtureTransport(
        Response(200, b'{"uploadId":"attempt-1","key":"storage-key"}'),
        Response(200, b'{"url":"https://storage.example.com/part"}'),
        Response(200, headers={"etag": '"first"'}),
        Response(200, b'{}'),
        Response(200, b'{"id": null}'),
        Response(503, b'{"error":"cleanup unavailable"}'),
    )
    source = tmp_path / "roads.geojson"
    source.write_bytes(b'{}')
    client = GeoDelClient("https://example.com", "synthetic-key", "0.1.0", transport)
    with pytest.raises(GeoDelError, match="invalid upload response"):
        client.upload_file(source, source.name, "workspace-1")
    assert transport.calls[-1][0] == "DELETE"
    assert transport.calls[2][2].get("headers", {}) == {}
    assert transport.calls[3][2]["json"] == {"parts": [{"PartNumber": 1, "ETag": '"first"'}]}


def test_poll_cancellation_interrupts_status_request(tmp_path):
    import pytest
    from geodel.client import UploadCanceled
    from geodel.transport import Response, TransportCanceled

    class CancelStatus(FixtureTransport):
        def request(self, method, url, **options):
            if url.endswith("/status"):
                assert options["is_canceled"] is canceled
                raise TransportCanceled("canceled")
            return super().request(method, url, **options)

    canceled = lambda: False
    transport = CancelStatus(
        Response(200, b'{"uploadId":"attempt-1","key":"storage-key"}'),
        Response(200, b'{"url":"https://storage.example.com/part"}'),
        Response(200, headers={"ETag": '"first"'}),
        Response(200, b'{}'),
        Response(200, b'{"id":"upload-1"}'),
    )
    source = tmp_path / "roads.geojson"
    source.write_bytes(b'{}')
    client = GeoDelClient("https://example.com", "synthetic-key", "0.1.0", transport)
    with pytest.raises(UploadCanceled):
        client.publish_file(source, source.name, "workspace-1", is_canceled=canceled)


def test_client_failure_messages_hide_submitted_key():
    import pytest
    from geodel.client import GeoDelError
    from geodel.transport import Response, TransportError

    for outcome in (
        Response(500, b'{"message":"rejected synthetic-key"}'),
        TransportError("Network failure for Bearer synthetic-key"),
        Response(200, b'{"broken":"synthetic-key"'),
    ):
        client = GeoDelClient("https://example.com", "synthetic-key", "0.1.0", FixtureTransport(outcome))
        with pytest.raises(GeoDelError) as error:
            client.list_organizations()
        assert "synthetic-key" not in str(error.value)


def test_missing_etag_attempts_cleanup_and_preserves_original_failure(tmp_path):
    import pytest
    from geodel.client import GeoDelError
    from geodel.transport import Response, TransportTimeout

    transport = FixtureTransport(
        Response(200, b'{"uploadId":"attempt-1","key":"storage-key"}'),
        Response(200, b'{"url":"https://storage.example.com/part"}'),
        Response(200),
        TransportTimeout("cleanup timeout"),
    )
    source = tmp_path / "roads.geojson"
    source.write_bytes(b'{}')
    client = GeoDelClient("https://example.com", "synthetic-key", "0.1.0", transport)
    with pytest.raises(GeoDelError, match="no ETag"):
        client.upload_file(source, source.name, "workspace-1")
    assert transport.calls[-1][0] == "DELETE"
    assert transport.calls[-1][2]["timeout"] == 15


def test_invalid_payload_is_distinct_from_network_failure():
    import pytest
    from geodel.client import GeoDelError, ServerUnavailableError
    from geodel.transport import Response

    for body in (b"[]", b'{"organizations":null}', b"invalid JSON", b"\xff"):
        client = GeoDelClient("https://example.com", "synthetic-key", "0.1.0",
                              FixtureTransport(Response(200, body)))
        with pytest.raises(GeoDelError) as error:
            client.list_organizations()
        assert not isinstance(error.value, ServerUnavailableError)
