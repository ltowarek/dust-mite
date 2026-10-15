import dataclasses
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast

import pytest
import requests
from opentelemetry.proto.collector.profiles.v1development import (
    profiles_service_pb2,
)
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

from otlp_profiler import exporter
from otlp_profiler.aggregator import SampleKey

_STACK_A = (("main", "app.py", 10), ("busy", "app.py", 20))
_STACK_B = (("main", "app.py", 10),)


def _sample_counts() -> dict[SampleKey, int]:
    return {
        (_STACK_A, "MainThread", None): 3,
        (
            _STACK_B,
            "worker-1",
            (0x0102030405060708090A0B0C0D0E0F10, 0x1234ABCD5678EF90),
        ): 1,
    }


@dataclasses.dataclass(frozen=True)
class _RecordedRequest:
    path: str
    body: bytes
    headers: dict[str, str]


class _CollectorServer(ThreadingHTTPServer):
    """A real local HTTP server standing in for the OTel Collector."""

    received: list[_RecordedRequest]
    response_status: int


class _CollectorSpy(BaseHTTPRequestHandler):
    """Records each POST on its server and replies with `response_status`."""

    def do_POST(self) -> None:
        server = cast("_CollectorServer", self.server)
        length = int(self.headers["Content-Length"])
        server.received.append(
            _RecordedRequest(self.path, self.rfile.read(length), dict(self.headers))
        )
        self.send_response(server.response_status)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        """Silence the default per-request stderr logging."""


@pytest.fixture
def collector() -> Iterator[_CollectorServer]:
    server = _CollectorServer(("127.0.0.1", 0), _CollectorSpy)
    server.received = []
    server.response_status = 200
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()


_PROFILES_PATH = "/collector/profiles"


def _endpoint(server: _CollectorServer) -> str:
    host, port = server.server_address
    assert isinstance(host, str)
    return f"http://{host}:{port}{_PROFILES_PATH}"


_SETTINGS = exporter.ProfileSettings(Resource({SERVICE_NAME: "svc"}), sample_rate=100)
_WINDOW = exporter.ProfileWindow(
    time_unix_nano=1_700_000_000_000_000_000, duration_nano=500_000_000
)


class TestExport:
    def test_does_nothing_when_counts_are_empty(
        self, collector: _CollectorServer
    ) -> None:
        exporter.export({}, _SETTINGS, _WINDOW, _endpoint(collector))

        assert collector.received == []

    def test_posts_protobuf_to_the_endpoint_as_given(
        self, collector: _CollectorServer
    ) -> None:
        exporter.export(_sample_counts(), _SETTINGS, _WINDOW, _endpoint(collector))

        assert len(collector.received) == 1
        request = collector.received[0]
        assert request.path == _PROFILES_PATH
        assert request.headers["Content-Type"] == "application/x-protobuf"
        # raises if not a valid ExportProfilesServiceRequest
        profiles_service_pb2.ExportProfilesServiceRequest.FromString(request.body)

    def test_raises_when_collector_returns_an_error_status(
        self, collector: _CollectorServer
    ) -> None:
        collector.response_status = 500

        with pytest.raises(requests.exceptions.HTTPError):
            exporter.export(_sample_counts(), _SETTINGS, _WINDOW, _endpoint(collector))
