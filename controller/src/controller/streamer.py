"""streamer module: serves the car's feeds and drive endpoint to local clients."""

import contextlib
import dataclasses
import functools
import http
import json
import logging
import os
import select
import socket
import threading
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Any, Protocol, Self, cast, override

import websockets.exceptions
import websockets.sync.server
from opentelemetry import trace
from opentelemetry.semconv.attributes.client_attributes import CLIENT_ADDRESS
from opentelemetry.semconv.attributes.http_attributes import (
    HTTP_REQUEST_METHOD,
    HTTP_RESPONSE_STATUS_CODE,
    HttpRequestMethodValues,
)
from opentelemetry.semconv.attributes.network_attributes import NETWORK_PROTOCOL_NAME
from opentelemetry.semconv.attributes.url_attributes import URL_PATH
from websockets.frames import CloseCode

from .car import CarFeed, send_commands_to_car
from .collision_monitor import CollisionMonitor
from .command_arbiter import CommandArbiter, DriverAlreadyConnectedError
from .metrics import record_telemetry_received, record_viewer_camera_frame_sent
from .mjpeg import CONTENT_TYPE, CameraStreamPart, MjpegClient, format_part
from .observability import ObservabilitySettings, configure_observability
from .subject import Subject
from .tracing import extract_trace_context, inject_trace_context
from .vision import process_camera_frame
from .websocket_client import WebSocketClient
from .websocket_message import WebSocketMessage

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

tracer = trace.get_tracer(__name__)

# How long an idle client handler waits for a message before rechecking
# whether its client has disconnected.
_OUTBOX_POLL_S = 0.2


class _Feed[M](Protocol):
    def subscription(
        self, callback: Callable[[M], None]
    ) -> contextlib.AbstractContextManager[None]: ...


class _Outbox[M]:
    """One client's view of some feeds, keeping the newest message of each kind.

    Use as a context manager: it subscribes to `feeds` on entry and
    unsubscribes on exit. A client that falls behind skips stale camera
    frames and telemetry instead of stalling the feed that every other client
    shares.
    """

    def __init__(self, *feeds: _Feed[M], kind: Callable[[M], str]) -> None:
        self._feeds = feeds
        self._kind = kind
        self._subscriptions = contextlib.ExitStack()
        self._condition = threading.Condition()
        self._pending: dict[str, M] = {}

    def __enter__(self) -> Self:
        # Unsubscribes from the feeds already entered if a later one fails.
        with contextlib.ExitStack() as subscriptions:
            for feed in self._feeds:
                subscriptions.enter_context(feed.subscription(self._put))
            self._subscriptions = subscriptions.pop_all()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: TracebackType | None,
    ) -> None:
        self._subscriptions.close()

    def take(self, timeout: float) -> list[M]:
        with self._condition:
            self._condition.wait_for(lambda: self._pending, timeout)
            messages = list(self._pending.values())
            self._pending.clear()
            return messages

    def _put(self, message: M) -> None:
        with self._condition:
            self._pending[self._kind(message)] = message
            self._condition.notify()


TELEMETRY_PATH = "/telemetry"
DRIVE_PATH = "/drive"


@tracer.start_as_current_span("streamer.server_handler", kind=trace.SpanKind.SERVER)
def server_handler(
    telemetry: CarFeed[str | bytes, WebSocketMessage],
    arbiter: CommandArbiter,
    websocket: websockets.sync.server.ServerConnection,
) -> None:
    """WebSocket handler for incoming requests, routed by path."""
    span = trace.get_current_span()
    span.set_attribute(NETWORK_PROTOCOL_NAME, "websocket")

    path = websocket.request.path if websocket.request is not None else ""
    span.set_attribute(URL_PATH, path)
    logger.info("Server connection from: %s to %s", websocket.remote_address[0], path)

    try:
        if path == TELEMETRY_PATH:
            _serve_telemetry(websocket, telemetry, arbiter.collision_state)
        elif path == DRIVE_PATH:
            _serve_driver(arbiter, websocket)
        else:
            websocket.close(CloseCode.POLICY_VIOLATION, f"unknown path: {path}")
    except websockets.exceptions.ConnectionClosed:
        pass
    logger.info("Server connection closed")


def _serve_driver(
    arbiter: CommandArbiter, websocket: websockets.sync.server.ServerConnection
) -> None:
    try:
        with arbiter.claim() as submit:
            for message in websocket:
                submit(json.loads(message))
    except DriverAlreadyConnectedError as e:
        websocket.close(CloseCode.TRY_AGAIN_LATER, str(e))


def _serve_telemetry(
    websocket: websockets.sync.server.ServerConnection,
    telemetry: CarFeed[str | bytes, WebSocketMessage],
    collision_state: Subject[WebSocketMessage],
) -> None:
    with _Outbox(telemetry, collision_state, kind=lambda m: m["type"]) as outbox:
        _send_until_closed(websocket, outbox)


def _send_until_closed(
    websocket: websockets.sync.server.ServerConnection,
    outbox: _Outbox[WebSocketMessage],
) -> None:
    while websocket.close_code is None:
        for message in outbox.take(timeout=_OUTBOX_POLL_S):
            websocket.send(json.dumps(message))


CAMERA_PATH = "/camera"
DEFAULT_CAMERA_PORT = 8766


class CameraServer(ThreadingHTTPServer):
    """Serves the processed Camera stream to viewers as MJPEG on `CAMERA_PATH`."""

    def __init__(
        self,
        address: tuple[str, int],
        camera: CarFeed[CameraStreamPart, CameraStreamPart],
    ) -> None:
        """Initialize the object; it reads `camera` only while a viewer watches."""
        super().__init__(address, _ViewerHandler)
        self.camera = camera


class _ViewerHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != CAMERA_PATH:
            self.send_error(http.HTTPStatus.NOT_FOUND)
            return
        _serve_viewer(self, cast("CameraServer", self.server).camera)

    @override
    def log_message(self, *args: object) -> None:
        """Log through the module logger, not stderr."""
        logger.debug("Viewer %s: %s", self.client_address[0], args)


@tracer.start_as_current_span(f"GET {CAMERA_PATH}", kind=trace.SpanKind.SERVER)
def _serve_viewer(
    viewer: BaseHTTPRequestHandler, camera: CarFeed[CameraStreamPart, CameraStreamPart]
) -> None:
    span = trace.get_current_span()
    span.set_attribute(HTTP_REQUEST_METHOD, HttpRequestMethodValues.GET.value)
    span.set_attribute(URL_PATH, CAMERA_PATH)
    span.set_attribute(CLIENT_ADDRESS, viewer.client_address[0])
    viewer.send_response(http.HTTPStatus.OK)
    viewer.send_header("Content-Type", CONTENT_TYPE)
    viewer.send_header("Cache-Control", "no-store")
    viewer.end_headers()
    span.set_attribute(HTTP_RESPONSE_STATUS_CODE, http.HTTPStatus.OK)
    with (
        _Outbox(camera, kind=lambda _: "camera") as outbox,
        contextlib.suppress(BrokenPipeError, ConnectionResetError),
    ):
        while not _viewer_left(viewer.connection):
            for part in outbox.take(timeout=_OUTBOX_POLL_S):
                _send_part(viewer, part)


def _viewer_left(connection: socket.socket) -> bool:
    """Whether the viewer closed its connection; it sends nothing after its request."""
    readable, _, _ = select.select([connection], [], [], 0)
    return bool(readable) and not connection.recv(1, socket.MSG_PEEK)


def _send_part(viewer: BaseHTTPRequestHandler, part: CameraStreamPart) -> None:
    with tracer.start_as_current_span(
        "streamer.send_camera_frame",
        context=extract_trace_context(part.headers),
        kind=trace.SpanKind.PRODUCER,
    ) as span:
        span.set_attribute(CLIENT_ADDRESS, viewer.client_address[0])
        viewer.wfile.write(
            format_part(CameraStreamPart(inject_trace_context({}), part.jpeg))
        )
        viewer.wfile.flush()
    record_viewer_camera_frame_sent()


def relay_camera_part(part: CameraStreamPart) -> CameraStreamPart:
    """Turn one Camera stream part from the car into a processed one for viewers."""
    car_context = extract_trace_context(part.headers)
    with tracer.start_as_current_span(
        "streamer.handle_camera_frame", context=car_context
    ) as span:
        span.set_attribute(NETWORK_PROTOCOL_NAME, "http")
        return CameraStreamPart(
            inject_trace_context({}), process_camera_frame(part.jpeg)
        )


def relay_telemetry_message(raw: str | bytes) -> WebSocketMessage:
    """Turn one telemetry message from the car into a telemetry message for clients."""
    telemetry: dict[str, Any] = json.loads(raw)
    record_telemetry_received()
    car_context = extract_trace_context(telemetry)
    with tracer.start_as_current_span(
        "streamer.handle_telemetry", context=car_context
    ) as span:
        span.set_attribute(NETWORK_PROTOCOL_NAME, "websocket")
        return prepare_telemetry_message(telemetry)


@dataclasses.dataclass(frozen=True)
class StreamerSettings:
    """The streamer's settings, read from the environment."""

    camera_uri: str
    telemetry_uri: str
    drive_uri: str
    camera_port: int
    observability: ObservabilitySettings

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> Self:
        """Read the settings from `environ`; the car endpoint URIs are required."""
        return cls(
            camera_uri=environ["STREAM_CLIENT_URI"],
            telemetry_uri=environ["TELEMETRY_CLIENT_URI"],
            drive_uri=environ["DRIVE_CLIENT_URI"],
            camera_port=int(
                environ.get("STREAMER_CAMERA_PORT", str(DEFAULT_CAMERA_PORT))
            ),
            observability=ObservabilitySettings.from_env(environ),
        )


def prepare_telemetry_message(telemetry: dict[str, Any]) -> WebSocketMessage:
    """Build a telemetry message with trace context."""
    message = {"type": "telemetry", "data": telemetry}
    return inject_trace_context(message)


def main() -> None:
    """Run the main entry point."""
    settings = StreamerSettings.from_env(os.environ)
    configure_observability("dust-mite-streamer", settings.observability)
    commands: Subject[WebSocketMessage] = Subject()
    camera = CarFeed(
        functools.partial(MjpegClient, settings.camera_uri), relay_camera_part
    )
    telemetry = CarFeed(
        functools.partial(WebSocketClient, settings.telemetry_uri, "r"),
        relay_telemetry_message,
    )
    arbiter = CommandArbiter(commands, telemetry, CollisionMonitor())
    handler = functools.partial(server_handler, telemetry, arbiter)
    try:
        with (
            send_commands_to_car(settings.drive_uri, commands),
            CameraServer(("0.0.0.0", settings.camera_port), camera) as viewers,  # noqa: S104 - intentional, streamer must accept connections from all interfaces
            websockets.sync.server.serve(handler, "0.0.0.0", 8765) as server,  # noqa: S104 - intentional, streamer must accept connections from all interfaces
        ):
            viewers_thread = threading.Thread(target=viewers.serve_forever)
            viewers_thread.start()
            logger.info("Starting server")
            try:
                server.serve_forever()
            finally:
                viewers.shutdown()
                viewers_thread.join()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    logger.info("Shutting down server")
    server.shutdown()


if __name__ == "__main__":
    main()
