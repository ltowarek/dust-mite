"""Test doubles for the OTel Collector the profiler exports to."""

import dataclasses
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast, override

__test__ = False

PROFILES_PATH = "/collector/profiles"


@dataclasses.dataclass(frozen=True)
class RecordedRequest:
    path: str
    body: bytes
    headers: dict[str, str]


class CollectorServer(ThreadingHTTPServer):
    """A real local HTTP server standing in for the OTel Collector."""

    received: list[RecordedRequest]
    response_status: int

    @property
    def profiles_endpoint(self) -> str:
        """Return the full OTLP/HTTP profiles URL this server accepts."""
        host, port = self.server_address[:2]
        return f"http://{host!s}:{port}{PROFILES_PATH}"


class CollectorSpy(BaseHTTPRequestHandler):
    """Records each POST on its server and replies with `response_status`."""

    def do_POST(self) -> None:
        server = cast("CollectorServer", self.server)
        length = int(self.headers["Content-Length"])
        server.received.append(
            RecordedRequest(self.path, self.rfile.read(length), dict(self.headers))
        )
        self.send_response(server.response_status)
        self.end_headers()

    @override
    def log_message(self, *args: object) -> None:
        """Silence the default per-request stderr logging."""
