"""streamer module: serves the car's feeds and drive endpoint to local clients."""

import asyncio
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
from collections.abc import AsyncIterator, Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Any, Self, cast, override

import websockets.asyncio.server
import websockets.exceptions
from opentelemetry import trace
from opentelemetry.semconv.attributes.client_attributes import CLIENT_ADDRESS
from opentelemetry.semconv.attributes.http_attributes import (
    HTTP_REQUEST_METHOD,
    HTTP_RESPONSE_STATUS_CODE,
    HttpRequestMethodValues,
)
from opentelemetry.semconv.attributes.network_attributes import NETWORK_PROTOCOL_NAME
from opentelemetry.semconv.attributes.url_attributes import URL_PATH
from websockets.asyncio.client import ClientConnection
from websockets.frames import CloseCode

from .car import CarFeed
from .collision_monitor import CollisionMonitor
from .command_arbiter import CommandArbiter, DriverAlreadyConnectedError
from .metrics import record_telemetry_received, record_viewer_camera_frame_sent
from .mjpeg import CONTENT_TYPE, CameraStreamPart, MjpegClient, format_part
from .observability import ObservabilitySettings, configure_observability
from .outbox import send_until_closed, subscribe_all
from .reconnecting_connection import forward, stay_connected
from .subject import Observable, Subject
from .tracing import extract_trace_context, inject_trace_context
from .vision import process_camera_frame
from .websocket_message import WebSocketMessage

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

tracer = trace.get_tracer(__name__)

# How long an idle Viewer handler waits for a Camera frame before rechecking
# whether its Viewer has disconnected.
_OUTBOX_POLL_S = 0.2


class _ThreadedOutbox[M]:
    """An `Outbox` for Viewer threads, whose sources publish from other threads."""

    def __init__(self, *sources: Observable[M]) -> None:
        self._sources = sources
        self._subscriptions = contextlib.ExitStack()
        self._condition = threading.Condition()
        self._pending: dict[int, M] = {}

    def __enter__(self) -> Self:
        self._subscriptions = subscribe_all(self._sources, self._put)
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

    def _put(self, slot: int, message: M) -> None:
        with self._condition:
            self._pending[slot] = message
            self._condition.notify()


TELEMETRY_PATH = "/telemetry"
DRIVE_PATH = "/drive"


@tracer.start_as_current_span("streamer.server_handler", kind=trace.SpanKind.SERVER)
async def server_handler(
    telemetry: Observable[WebSocketMessage],
    arbiter: CommandArbiter,
    websocket: websockets.asyncio.server.ServerConnection,
) -> None:
    """WebSocket handler for incoming requests, routed by path."""
    span = trace.get_current_span()
    span.set_attribute(NETWORK_PROTOCOL_NAME, "websocket")

    path = websocket.request.path if websocket.request is not None else ""
    span.set_attribute(URL_PATH, path)
    logger.info("Server connection from: %s to %s", websocket.remote_address[0], path)

    try:
        if path == TELEMETRY_PATH:
            await _serve_telemetry(websocket, telemetry, arbiter.collision_state)
        elif path == DRIVE_PATH:
            await _serve_driver(arbiter, websocket)
        else:
            await websocket.close(CloseCode.POLICY_VIOLATION, f"unknown path: {path}")
    except websockets.exceptions.ConnectionClosed:
        pass
    logger.info("Server connection closed")


async def _serve_driver(
    arbiter: CommandArbiter, websocket: websockets.asyncio.server.ServerConnection
) -> None:
    try:
        with arbiter.claim() as submit:
            async for message in websocket:
                submit(json.loads(message))
    except DriverAlreadyConnectedError as e:
        await websocket.close(CloseCode.TRY_AGAIN_LATER, str(e))


async def _serve_telemetry(
    websocket: websockets.asyncio.server.ServerConnection,
    telemetry: Observable[WebSocketMessage],
    collision_state: Subject[WebSocketMessage],
) -> None:
    await send_until_closed(websocket, telemetry, collision_state)


CAMERA_PATH = "/camera"
DEFAULT_CAMERA_PORT = 8766
DEFAULT_WEBSOCKET_PORT = 8765


class CameraServer(ThreadingHTTPServer):
    """Serves the processed Camera stream to viewers as MJPEG on `CAMERA_PATH`."""

    def __init__(
        self,
        address: tuple[str, int],
        camera: CarFeed[CameraStreamPart],
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
    viewer: BaseHTTPRequestHandler, camera: CarFeed[CameraStreamPart]
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
        _ThreadedOutbox(camera) as outbox,
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


# Turns one Camera frame, a JPEG, into the one viewers see.
type CameraFrameProcessor = Callable[[bytes], bytes]


def relay_camera_part(
    part: CameraStreamPart, process: CameraFrameProcessor = process_camera_frame
) -> CameraStreamPart:
    """Turn one Camera stream part from the car into a processed one for viewers."""
    car_context = extract_trace_context(part.headers)
    with tracer.start_as_current_span(
        "streamer.handle_camera_frame", context=car_context
    ) as span:
        span.set_attribute(NETWORK_PROTOCOL_NAME, "http")
        return CameraStreamPart(inject_trace_context({}), process(part.jpeg))


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
    listen_host: str = "0.0.0.0"  # noqa: S104 - intentional, streamer must accept connections from all interfaces
    websocket_port: int = DEFAULT_WEBSOCKET_PORT

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


@dataclasses.dataclass(frozen=True)
class StreamerEndpoints:
    """The URL of each Streamer endpoint, at the address its server is bound to."""

    drive: str
    telemetry: str
    camera: str


@contextlib.asynccontextmanager
async def serve_streamer(
    settings: StreamerSettings, process: CameraFrameProcessor = process_camera_frame
) -> AsyncIterator[StreamerEndpoints]:
    """Serve the Streamer endpoints while the context is open; port 0 binds any."""
    commands: Subject[WebSocketMessage] = Subject()
    camera = CarFeed(
        functools.partial(MjpegClient, settings.camera_uri),
        functools.partial(relay_camera_part, process=process),
    )
    async with asyncio.TaskGroup() as tasks:
        telemetry: Subject[WebSocketMessage] = Subject()
        telemetry_task = tasks.create_task(
            _publish_telemetry(settings.telemetry_uri, telemetry)
        )
        arbiter = CommandArbiter(commands, telemetry, CollisionMonitor())
        handler = functools.partial(server_handler, telemetry, arbiter)
        car_drive_task = tasks.create_task(forward(settings.drive_uri, commands))
        try:
            async with (
                websockets.asyncio.server.serve(
                    handler, settings.listen_host, settings.websocket_port
                ) as websocket_server,
                _serve_camera(
                    CameraServer((settings.listen_host, settings.camera_port), camera)
                ) as camera_url,
            ):
                websocket_host, websocket_port = websocket_server.sockets[
                    0
                ].getsockname()[:2]
                websocket_url = f"ws://{websocket_host}:{websocket_port}"
                yield StreamerEndpoints(
                    drive=f"{websocket_url}{DRIVE_PATH}",
                    telemetry=f"{websocket_url}{TELEMETRY_PATH}",
                    camera=camera_url,
                )
        finally:
            car_drive_task.cancel()
            telemetry_task.cancel()


async def _publish_telemetry(uri: str, telemetry: Subject[WebSocketMessage]) -> None:
    async def publish_all(connection: ClientConnection) -> None:
        async for message in connection:
            try:
                telemetry.publish(relay_telemetry_message(message))
            except Exception:
                logger.exception("Dropping a Telemetry message from the car")

    await stay_connected(uri, publish_all)


@contextlib.asynccontextmanager
async def _serve_camera(server: CameraServer) -> AsyncIterator[str]:
    """Run `server` on its own thread beside the event loop; yield its Camera URL."""
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host!s}:{port}{CAMERA_PATH}"
    finally:
        await asyncio.to_thread(_stop_camera_server, server, thread)


def _stop_camera_server(server: CameraServer, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join()
    server.server_close()


async def _serve_until_cancelled(settings: StreamerSettings) -> None:
    async with serve_streamer(settings):
        logger.info("Starting server")
        await asyncio.Event().wait()


def main() -> None:
    """Run the main entry point."""
    settings = StreamerSettings.from_env(os.environ)
    configure_observability("dust-mite-streamer", settings.observability)
    try:
        asyncio.run(_serve_until_cancelled(settings))
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    logger.info("Shutting down server")


if __name__ == "__main__":
    main()
