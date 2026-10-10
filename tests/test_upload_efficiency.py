"""Upload policy and concurrency checks at the real client boundary."""
from dataclasses import replace
from contextlib import nullcontext
import json
from pathlib import Path
from threading import Barrier, Event, Lock
from urllib.parse import urlparse

import pytest

from geodel import client as module
from geodel.client import GeoDelClient, GeoDelError, UploadCanceled
from geodel.transport import Response, TransportCanceled, TransportError, TransportTimeout


class UploadTransport:
    def __init__(self):
        self.calls = []
        self.parts = {}
        self.completed = None
        self.put_hook = None
        self.lock = Lock()

    def session(self):
        return nullcontext()

    def request(self, method, url, **options):
        with self.lock:
            self.calls.append((method, url, options))
        path = urlparse(url).path
        if method == "PUT":
            if self.put_hook:
                outcome = self.put_hook(url, options)
                if outcome is not None:
                    return outcome
            data = options["data"]
            data = data.read_bytes() if isinstance(data, Path) else data
            with self.lock:
                self.parts[path] = data
            if options.get("upload_progress"):
                options["upload_progress"](len(data))
            return Response(200, headers={"ETag": f'"{path}"'})
        if path.endswith("/params"):
            assert options["params"]["metadata[format]"] == "geojson"
            payload = {"attemptId": "attempt", "method": "PUT", "url": "https://storage.example/single",
                       "headers": {"Content-Type": "application/geo+json"}, "fields": {"key": "attempt"}}
        elif path.endswith("/multipart"):
            payload = {"uploadId": "attempt", "key": "attempt"}
        elif path.endswith("/complete"):
            self.completed = options["json"]["parts"]
            payload = {}
        elif path.endswith("/register"):
            payload = {"id": "upload"}
        elif method == "DELETE":
            payload = {}
        else:
            payload = {"url": "https://storage.example/" + path.rsplit("/", 1)[1]}
        return Response(200, json.dumps(payload).encode())


def client(transport, config=None):
    return GeoDelClient("https://api.example", "synthetic-key", "0.1.2", transport, config=config)


@pytest.mark.parametrize("limit_bytes, label", [
    (100 * 1024**2, "100 MiB"),
    (300 * 1024**2, "300 MiB"),
    (200 * 1024**2 + 1, "209,715,201 bytes"),
])
def test_configured_file_cap_accepts_boundary_and_rejects_next_byte(tmp_path, limit_bytes, label):
    config = replace(module.DEFAULT_CONFIG, max_file_size_bytes=limit_bytes)
    path = tmp_path / "roads.geojson"
    transport = UploadTransport()
    transport.put_hook = lambda *_: Response(200, headers={"ETag": "part"})
    with path.open("wb") as source:
        source.truncate(config.max_file_size_bytes)
    uploader = client(transport, config)
    assert uploader.upload_file(path, path.name, "org") == "upload"
    transport.calls.clear()
    with path.open("wb") as source:
        source.truncate(config.max_file_size_bytes + 1)
    with pytest.raises(GeoDelError, match=label):
        uploader.upload_file(path, path.name, "org")
    assert transport.calls == []


def test_configured_extensions_and_name_limit_are_enforced_before_requests(tmp_path):
    path = tmp_path / "roads.geojson"
    path.write_bytes(b"{}")
    config = replace(module.DEFAULT_CONFIG, allowed_extensions=(".json",), max_filename_length=13)
    transport = UploadTransport()
    uploader = client(transport, config)
    with pytest.raises(GeoDelError, match="formats are .json"):
        uploader.upload_file(path, "roads.geojson", "org")
    with pytest.raises(GeoDelError, match="13 characters"):
        uploader.upload_file(path, "123456789.json", "org")
    assert transport.calls == []


def test_configured_transfer_tuning_and_timeouts_are_used(tmp_path, monkeypatch):
    path = tmp_path / "roads.geojson"
    path.write_bytes(b"123456789")
    transport = UploadTransport()
    config = replace(module.DEFAULT_CONFIG, single_put_threshold_bytes=8, part_size_bytes=4,
                     part_concurrency=1, request_timeout_seconds=23, upload_part_timeout_seconds=123,
                     retry_delays_seconds=(0,))
    monkeypatch.setattr(module, "sleep", lambda _: None)
    attempts = []
    def put(url, _options):
        attempts.append(url)
        if len(attempts) == 1:
            return Response(503)
    transport.put_hook = put
    assert client(transport, config).upload_file(path, path.name, "org") == "upload"
    assert [len(transport.parts[f"/{n}"]) for n in range(1, 4)] == [4, 4, 1]
    assert attempts == ["https://storage.example/1", "https://storage.example/1",
                        "https://storage.example/2", "https://storage.example/3"]
    assert all(options["timeout"] == (123 if method == "PUT" else 23)
               for method, _, options in transport.calls)


def test_small_file_streams_without_multipart_and_registers_last(tmp_path):
    path = tmp_path / "roads.geojson"
    path.write_bytes(b'{"features":[]}')
    transport = UploadTransport()
    progress = []
    assert client(transport).upload_file(path, path.name, "org", "folder", progress.append) == "upload"
    assert [call[0] for call in transport.calls] == ["GET", "PUT", "POST"]
    put = transport.calls[1][2]
    assert put["data"] == path
    assert put["headers"] == {"Content-Type": "application/geo+json"}
    assert transport.calls[-1][2]["json"] == {"attemptId": "attempt", "folderId": "folder"}
    assert progress[-1] == 100
    assert all(value < 100 for value in progress[:-1])


@pytest.mark.parametrize("size,multipart", [(100 * 1024**2, False), (100 * 1024**2 + 1, True)])
def test_single_put_threshold(tmp_path, size, multipart):
    path = tmp_path / "roads.geojson"
    with path.open("wb") as source:
        source.truncate(size)
    transport = UploadTransport()
    transport.put_hook = lambda *_: Response(200, headers={"ETag": "part"})
    assert client(transport).upload_file(path, path.name, "org") == "upload"
    assert (transport.completed is not None) == multipart


def test_three_parts_overlap_and_complete_in_order(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DEFAULT_CONFIG", replace(module.DEFAULT_CONFIG, single_put_threshold_bytes=0))
    monkeypatch.setattr(module, "DEFAULT_CONFIG", replace(module.DEFAULT_CONFIG, part_size_bytes=8))
    path = tmp_path / "roads.geojson"
    original = bytes(range(47))
    path.write_bytes(original)
    transport = UploadTransport()
    barrier = Barrier(3)
    transport.put_hook = lambda *_: (barrier.wait(timeout=1), None)[1]
    progress = []
    assert client(transport).upload_file(path, path.name, "org", progress=progress.append) == "upload"
    assert b"".join(transport.parts[f"/{n}"] for n in range(1, 7)) == original
    assert [part["PartNumber"] for part in transport.completed] == list(range(1, 7))
    assert progress == sorted(progress)
    assert progress[-1] == 100


def test_at_most_three_part_buffers_remain_live(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DEFAULT_CONFIG", replace(module.DEFAULT_CONFIG, single_put_threshold_bytes=0))
    monkeypatch.setattr(module, "DEFAULT_CONFIG", replace(module.DEFAULT_CONFIG, part_size_bytes=8))
    path = tmp_path / "roads.geojson"
    path.write_bytes(b"x" * 72)
    transport = UploadTransport()
    barrier = Barrier(3)
    counts = {"live": 0, "peak": 0}
    class Part(bytes):
        def __new__(cls, data):
            with transport.lock:
                counts["live"] += 1
                counts["peak"] = max(counts.values())
            return super().__new__(cls, data)

        def __del__(self):
            with transport.lock:
                counts["live"] -= 1

    original_open = Path.open
    class Reader:
        def __init__(self):
            self.source = original_open(path, "rb")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.source.close()

        def seek(self, offset):
            self.source.seek(offset)

        def fileno(self):
            return self.source.fileno()

        def read(self, size):
            assert size <= 8
            return Part(self.source.read(size))

    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: Reader())
    original_request = transport.request
    def request(method, url, **options):
        if method == "PUT":
            barrier.wait(timeout=1)
            return Response(200, headers={"ETag": "part"})
        return original_request(method, url, **options)
    transport.request = request
    assert client(transport).upload_file(path, path.name, "org") == "upload"
    assert counts == {"live": 0, "peak": 3}


def test_transient_put_retries_same_attempt_and_progress_does_not_regress(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "sleep", lambda _: None)
    path = tmp_path / "roads.geojson"
    path.write_bytes(b"original bytes")
    transport = UploadTransport()
    attempts = []
    def fail_once(url, options):
        attempts.append(url)
        options["upload_progress"](5 if len(attempts) == 1 else 2)
        if len(attempts) == 1:
            raise TransportTimeout("transient fixture")
    transport.put_hook = fail_once
    progress = []
    assert client(transport).upload_file(path, path.name, "org", progress=progress.append) == "upload"
    assert attempts == ["https://storage.example/single"] * 2
    assert progress == sorted(progress)
    assert sum(url.endswith("/params") for _, url, _ in transport.calls) == 1


@pytest.mark.parametrize("status,attempts", [(503, 4), (429, 4), (403, 1)])
def test_put_retry_budget_and_permanent_failure(tmp_path, monkeypatch, status, attempts):
    monkeypatch.setattr(module, "sleep", lambda _: None)
    path = tmp_path / "roads.geojson"
    path.write_bytes(b"bytes")
    transport = UploadTransport()
    transport.put_hook = lambda *_: Response(status)
    with pytest.raises(GeoDelError):
        client(transport).upload_file(path, path.name, "org")
    assert sum(method == "PUT" for method, _, _ in transport.calls) == attempts
    assert not any(url.endswith("/register") for _, url, _ in transport.calls)


def test_cancel_during_retry_wait(tmp_path, monkeypatch):
    canceled = Event()
    monkeypatch.setattr(module, "sleep", lambda _: canceled.set())
    path = tmp_path / "roads.geojson"
    path.write_bytes(b"bytes")
    transport = UploadTransport()
    transport.put_hook = lambda *_: Response(503)
    with pytest.raises(UploadCanceled):
        client(transport).upload_file(path, path.name, "org", is_canceled=canceled.is_set)
    assert sum(method == "PUT" for method, _, _ in transport.calls) == 1


def test_failed_part_stops_siblings_before_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DEFAULT_CONFIG", replace(module.DEFAULT_CONFIG, single_put_threshold_bytes=0))
    monkeypatch.setattr(module, "DEFAULT_CONFIG", replace(module.DEFAULT_CONFIG, part_size_bytes=8))
    path = tmp_path / "roads.geojson"
    path.write_bytes(bytes(range(47)))
    transport = UploadTransport()
    barrier = Barrier(3)
    active = set()
    original_request = transport.request

    def put(url, options):
        with transport.lock:
            active.add(url)
        try:
            barrier.wait(timeout=1)
            if url.endswith("/1"):
                return Response(403)
            from time import monotonic, sleep
            deadline = monotonic() + 1
            while not options["is_canceled"]() and monotonic() < deadline:
                sleep(0.001)
            assert options["is_canceled"]()
            raise TransportCanceled("sibling stopped")
        finally:
            with transport.lock:
                active.remove(url)

    def request(method, url, **options):
        if method == "DELETE":
            assert not active
            assert not options["is_canceled"]()
        return original_request(method, url, **options)

    transport.put_hook = put
    transport.request = request
    with pytest.raises(GeoDelError, match="HTTP 403"):
        client(transport).upload_file(path, path.name, "org")
    assert sum(method == "PUT" for method, _, _ in transport.calls) == 3
    assert transport.calls[-1][0] == "DELETE"
    assert transport.completed is None


def test_retry_after_is_capped_and_honored(tmp_path, monkeypatch):
    waits = []
    monkeypatch.setattr(module, "sleep", waits.append)
    path = tmp_path / "roads.geojson"
    path.write_bytes(b"bytes")
    transport = UploadTransport()
    def put(_url, _options):
        if sum(method == "PUT" for method, _, _ in transport.calls) == 1:
            return Response(429, headers={"Retry-After": "120"})
    transport.put_hook = put
    assert client(transport).upload_file(path, path.name, "org") == "upload"
    assert sum(waits) == pytest.approx(30)


def test_part_signing_retries_without_creating_a_second_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DEFAULT_CONFIG", replace(module.DEFAULT_CONFIG, single_put_threshold_bytes=0))
    monkeypatch.setattr(module, "sleep", lambda _: None)
    path = tmp_path / "roads.geojson"
    path.write_bytes(b"bytes")
    transport = UploadTransport()
    original_request = transport.request
    signs = []
    def request(method, url, **options):
        response = original_request(method, url, **options)
        if method == "GET":
            signs.append(url)
            if len(signs) == 1:
                return Response(503)
        return response
    transport.request = request
    assert client(transport).upload_file(path, path.name, "org") == "upload"
    assert len(signs) == 2 and signs[0] == signs[1]
    assert sum(url.endswith("/multipart") for _, url, _ in transport.calls) == 1


def test_tls_failure_is_not_retried(tmp_path):
    path = tmp_path / "roads.geojson"
    path.write_bytes(b"bytes")
    transport = UploadTransport()
    def put(_url, _options):
        raise TransportError("TLS verification failure")
    transport.put_hook = put
    with pytest.raises(GeoDelError):
        client(transport).upload_file(path, path.name, "org")
    assert sum(method == "PUT" for method, _, _ in transport.calls) == 1


@pytest.mark.parametrize("stage", ["/complete", "/register"])
def test_finalization_is_not_retried(tmp_path, monkeypatch, stage):
    monkeypatch.setattr(module, "DEFAULT_CONFIG", replace(module.DEFAULT_CONFIG, single_put_threshold_bytes=0))
    path = tmp_path / "roads.geojson"
    path.write_bytes(b"bytes")
    transport = UploadTransport()
    original_request = transport.request
    def request(method, url, **options):
        response = original_request(method, url, **options)
        return Response(503) if url.endswith(stage) else response
    transport.request = request
    with pytest.raises(GeoDelError):
        client(transport).upload_file(path, path.name, "org")
    assert sum(url.endswith(stage) for _, url, _ in transport.calls) == 1
    assert transport.calls[-1][0] == "DELETE"


@pytest.mark.parametrize("multipart", [False, True])
@pytest.mark.parametrize("cancel_before_registration", [False, True])
def test_registration_finishes_if_cancel_arrives_after_it_starts(tmp_path, monkeypatch, multipart, cancel_before_registration):
    if multipart:
        monkeypatch.setattr(module, "DEFAULT_CONFIG", replace(module.DEFAULT_CONFIG, single_put_threshold_bytes=0))
    path = tmp_path / "roads.geojson"
    path.write_bytes(b"synthetic")
    canceled = Event()
    transport = UploadTransport()
    original_request = transport.request

    def request(method, url, **options):
        if url.endswith("/register"):
            assert not canceled.is_set()
            canceled.set()
            if options["is_canceled"]():
                raise TransportCanceled("Request canceled")
        response = original_request(method, url, **options)
        if cancel_before_registration and (url.endswith("/complete") or (not multipart and method == "PUT")):
            canceled.set()
        return response

    transport.request = request
    uploader = client(transport)
    uploader.is_canceled = canceled.is_set
    if cancel_before_registration:
        with pytest.raises(UploadCanceled):
            uploader.upload_file(path, path.name, "org")
        assert not any(url.endswith("/register") for _, url, _ in transport.calls)
    else:
        assert uploader.upload_file(path, path.name, "org") == "upload"
        assert canceled.is_set()


@pytest.mark.parametrize("mutation", ["same_size_edit", "replacement"])
@pytest.mark.parametrize("stage", ["initialization", "before_read", "after_read", "last_put", "before_completion"])
def test_multipart_source_mutations_abort_before_completion(tmp_path, monkeypatch, mutation, stage):
    monkeypatch.setattr(module, "DEFAULT_CONFIG", replace(module.DEFAULT_CONFIG, single_put_threshold_bytes=0))
    monkeypatch.setattr(module, "DEFAULT_CONFIG", replace(module.DEFAULT_CONFIG, part_size_bytes=8))
    monkeypatch.setattr(module, "DEFAULT_CONFIG", replace(module.DEFAULT_CONFIG, part_concurrency=1))
    path = tmp_path / "roads.geojson"
    path.write_bytes(b"x" * 24)
    transport = UploadTransport()
    uploader = client(transport)
    original_open = Path.open
    mutated = False

    def mutate():
        nonlocal mutated
        if mutated:
            return
        mutated = True
        if mutation == "same_size_edit":
            with original_open(path, "r+b") as stream:
                stream.write(b"y" * 24)
        else:
            replacement = path.with_suffix(".replacement")
            replacement.write_bytes(b"y" * 24)
            replacement.replace(path)

    class Reader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def seek(self, offset):
            self.stream.seek(offset)
            if stage == "before_read":
                mutate()

        def read(self, size):
            chunk = self.stream.read(size)
            if stage == "after_read":
                mutate()
            return chunk

    def open_source(file_path, mode="r", *args, **kwargs):
        stream = original_open(file_path, mode, *args, **kwargs)
        return Reader(stream) if file_path == path and mode == "rb" else stream

    monkeypatch.setattr(Path, "open", open_source)
    original_request = transport.request

    def request(method, url, **options):
        response = original_request(method, url, **options)
        if stage == "initialization" and url.endswith("/multipart"):
            mutate()
        if stage == "last_put" and method == "PUT" and url.endswith("/3"):
            mutate()
        return response

    transport.request = request
    original_upload_parts = uploader._upload_parts

    def upload_parts(*args):
        parts = original_upload_parts(*args)
        if stage == "before_completion":
            mutate()
        return parts

    monkeypatch.setattr(uploader, "_upload_parts", upload_parts)
    with pytest.raises(GeoDelError, match="Upload file changed"):
        uploader.upload_file(path, path.name, "org")
    assert mutated
    assert transport.completed is None
    assert not any(url.endswith("/register") for _, url, _ in transport.calls)
    assert transport.calls[-1][0] == "DELETE"
    if stage in ("initialization", "before_read", "after_read"):
        assert not transport.parts
