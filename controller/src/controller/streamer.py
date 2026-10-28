"""streamer module: serves the car's feeds and drive endpoint to local clients."""

import asyncio
import contextlib
import dataclasses
import functools
import http
import json
import logging
import os
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any, Self

import websockets.asyncio.server
import websockets.exceptions
from aiohttp import web
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
from .mjpeg import CONTENT_TYPE, CameraStreamPart, format_part, read_stream
from .observability import ObservabilitySettings, configure_observability
from .outbox import Outbox, send_until_closed
from .reconnecting_connection import forward, stay_connected
from .subject import Observable, Subject
from .tracing import extract_trace_context, inject_trace_context
from .vision import process_camera_frame
from .websocket_message import WebSocketMessage

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

tracer = trace.get_tracer(__name__)


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
            await send_until_closed(websocket, telemetry, arbiter.collision_state)
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


CAMERA_PATH = "/camera"
DEFAULT_CAMERA_PORT = 8766
DEFAULT_WEBSOCKET_PORT = 8765


@tracer.start_as_current_span(f"GET {CAMERA_PATH}", kind=trace.SpanKind.SERVER)
async def _serve_viewer(
    camera: Observable[CameraStreamPart], request: web.Request
) -> web.StreamResponse:
    span = trace.get_current_span()
    span.set_attribute(HTTP_REQUEST_METHOD, HttpRequestMethodValues.GET.value)
    span.set_attribute(URL_PATH, CAMERA_PATH)
    span.set_attribute(CLIENT_ADDRESS, request.remote or "")
    response = web.StreamResponse(
        headers={"Content-Type": CONTENT_TYPE, "Cache-Control": "no-store"}
    )
    await response.prepare(request)
    span.set_attribute(HTTP_RESPONSE_STATUS_CODE, http.HTTPStatus.OK)
    # A departing Viewer cancels this handler, even while no Camera frame flows.
    with Outbox(camera) as outbox, contextlib.suppress(ConnectionResetError):
        while True:
            for part in await outbox.take():
                await _send_part(response, part, request.remote or "")
    return response


async def _send_part(
    response: web.StreamResponse, part: CameraStreamPart, client_address: str
) -> None:
    with tracer.start_as_current_span(
        "streamer.send_camera_frame",
        context=extract_trace_context(part.headers),
        kind=trace.SpanKind.PRODUCER,
    ) as span:
        span.set_attribute(CLIENT_ADDRESS, client_address)
        await response.write(
            format_part(CameraStreamPart(inject_trace_context({}), part.jpeg))
        )
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


async def _relay_camera(
    uri: str,
    process: CameraFrameProcessor,
    publish: Callable[[CameraStreamPart], None],
) -> None:
    """Publish each Camera stream part from `uri`, processed, skipping stale ones."""
    unprocessed: Subject[CameraStreamPart] = Subject()
    with Outbox(unprocessed) as newest:
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(read_stream(uri, unprocessed.publish))
            while True:
                for part in await newest.take():
                    try:
                        relayed = await asyncio.to_thread(
                            relay_camera_part, part, process
                        )
                    except Exception:
                        logger.exception("Dropping an unreadable Camera frame")
                    else:
                        publish(relayed)


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
    async with asyncio.TaskGroup() as tasks:
        camera = CarFeed(
            functools.partial(_relay_camera, settings.camera_uri, process), tasks
        )
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
                    settings.listen_host, settings.camera_port, camera
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
                relayed = relay_telemetry_message(message)
            except Exception:
                logger.exception("Dropping a Telemetry message from the car")
            else:
                telemetry.publish(relayed)

    await stay_connected(uri, publish_all)


@contextlib.asynccontextmanager
async def _serve_camera(
    host: str, port: int, camera: Observable[CameraStreamPart]
) -> AsyncIterator[str]:
    """Serve the processed Camera stream on `CAMERA_PATH`; yield its URL."""
    app = web.Application()
    app.router.add_get(CAMERA_PATH, functools.partial(_serve_viewer, camera))
    # Viewer responses never end, so stopping cancels them; 0 would wait forever.
    cancel_viewers_after_s = 0.1
    runner = web.AppRunner(
        app, handler_cancellation=True, shutdown_timeout=cancel_viewers_after_s
    )
    await runner.setup()
    try:
        await web.TCPSite(runner, host, port).start()
        bound_host, bound_port = runner.addresses[0][:2]
        yield f"http://{bound_host}:{bound_port}{CAMERA_PATH}"
    finally:
        await runner.cleanup()


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
