"""Test doubles for the car: real HTTP and websocket endpoints standing in for its own.

Feed endpoints are stubs that send canned messages; every endpoint is a spy
that records its connections and the commands it receives.
"""

import contextlib
import dataclasses
import http
import json
import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, override

import cv2
import numpy as np
import websockets.exceptions
import websockets.http11
import websockets.sync.server

__test__ = False

FEED_INTERVAL_S = 0.05
CLEAR_DISTANCE_CM = 100
OBSTACLE_DISTANCE_CM = 3
CAR_TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"

ProcessRequest = (
    Callable[
        [websockets.sync.server.ServerConnection, websockets.http11.Request],
        websockets.http11.Response | None,
    ]
    | None
)


@dataclasses.dataclass
class CarEndpointSpy:
    """A car endpoint that records its connections and the commands it receives."""

    uri: str
    open_connections: int = 0
    peak_connections: int = 0
    received: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    _lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)

    @contextlib.contextmanager
    def connected(self) -> Iterator[None]:
        """Count one open connection while the context is open."""
        with self._lock:
            self.open_connections += 1
            self.peak_connections = max(self.peak_connections, self.open_connections)
        try:
            yield
        finally:
            with self._lock:
                self.open_connections -= 1


@contextlib.contextmanager
def serve(
    handler: Callable[[websockets.sync.server.ServerConnection], None],
    process_request: ProcessRequest = None,
) -> Iterator[websockets.sync.server.Server]:
    with websockets.sync.server.serve(
        handler, "localhost", 0, process_request=process_request
    ) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()


@contextlib.contextmanager
def car_endpoint_spy(
    serve_client: Callable[
        [websockets.sync.server.ServerConnection, CarEndpointSpy], None
    ],
    process_request: ProcessRequest = None,
) -> Iterator[CarEndpointSpy]:
    endpoint: CarEndpointSpy

    def handler(websocket: websockets.sync.server.ServerConnection) -> None:
        with (
            endpoint.connected(),
            contextlib.suppress(websockets.exceptions.ConnectionClosed),
        ):
            serve_client(websocket, endpoint)

    with serve(handler, process_request) as server:
        host, port = server.socket.getsockname()[:2]
        endpoint = CarEndpointSpy(f"ws://{host}:{port}")
        yield endpoint


def car_feed_stub(
    message: Callable[[], dict[str, Any]],
    process_request: ProcessRequest = None,
) -> contextlib.AbstractContextManager[CarEndpointSpy]:
    def push_messages(
        websocket: websockets.sync.server.ServerConnection, _: CarEndpointSpy
    ) -> None:
        while True:
            websocket.send(json.dumps(message()))
            time.sleep(FEED_INTERVAL_S)

    return car_endpoint_spy(push_messages, process_request)


def car_control_spy() -> contextlib.AbstractContextManager[CarEndpointSpy]:
    def record_commands(
        websocket: websockets.sync.server.ServerConnection, endpoint: CarEndpointSpy
    ) -> None:
        for message in websocket:
            endpoint.received.append(json.loads(message))

    return car_endpoint_spy(record_commands)


def camera_frame() -> bytes:
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    return bytes(cv2.imencode(".jpg", image)[1].tobytes())


def _mjpeg_part(jpeg: bytes) -> bytes:
    return (
        b"\r\n--frame\r\nContent-Type: image/jpeg\r\n"
        + f"Content-Length: {len(jpeg)}\r\n".encode()
        + f"traceparent: {CAR_TRACEPARENT}\r\n\r\n".encode()
        + jpeg
    )


@contextlib.contextmanager
def car_camera_stub(
    refusals: int = 0, *, stalled: bool = False
) -> Iterator[CarEndpointSpy]:
    """The car's Camera endpoint: answers `refusals` requests as busy, then streams.

    A `stalled` endpoint sends no parts until the client hangs up.
    """
    endpoint: CarEndpointSpy
    lock = threading.Lock()
    left = refusals

    def refuse() -> bool:
        nonlocal left
        with lock:
            left -= 1
            return left >= 0

    class CameraHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if refuse():
                self.send_error(http.HTTPStatus.SERVICE_UNAVAILABLE)
                return
            self.send_response(http.HTTPStatus.OK)
            self.send_header("Content-Type", "multipart/x-mixed-replace;boundary=frame")
            self.end_headers()
            with (
                endpoint.connected(),
                contextlib.suppress(BrokenPipeError, ConnectionResetError),
            ):
                if stalled:
                    self.rfile.read(1)
                    return
                while True:
                    self.wfile.write(_mjpeg_part(camera_frame()))
                    self.wfile.flush()
                    time.sleep(FEED_INTERVAL_S)

        @override
        def log_message(self, *args: object) -> None:
            """Silence the default per-request stderr logging."""

    with ThreadingHTTPServer(("localhost", 0), CameraHandler) as server:
        host, port = server.server_address[:2]
        endpoint = CarEndpointSpy(f"http://{host!s}:{port}/stream")
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield endpoint
        finally:
            server.shutdown()
            thread.join()


def telemetry(distance_ahead: int) -> Callable[[], dict[str, Any]]:
    return lambda: {"distance_ahead": distance_ahead, "speed": 0.0}
