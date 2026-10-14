"""streamer module: serves the car's feeds and drive endpoint to local clients."""

import base64
import contextlib
import dataclasses
import functools
import json
import logging
import os
import threading
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Self

import websockets.exceptions
import websockets.sync.server
from opentelemetry import trace
from websockets.frames import CloseCode

from .car import CarFeed, camera_frame_jpeg, send_commands_to_car
from .collision_monitor import CollisionMonitor
from .command_arbiter import CommandArbiter, DriverAlreadyConnectedError
from .metrics import record_telemetry_received
from .observability import ObservabilitySettings, configure_observability
from .subject import Subject
from .tracing import extract_trace_context, inject_trace_context
from .vision import process_frame

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

tracer = trace.get_tracer(__name__)

# How long an idle client handler waits for a message before rechecking
# whether its client has disconnected.
_OUTBOX_POLL_S = 0.2


class _Outbox:
    """One client's view of some feeds, keeping the newest message of each type.

    Use as a context manager: it subscribes to `feeds` on entry and
    unsubscribes on exit. A client that falls behind skips stale camera
    frames and telemetry instead of stalling the feed that every other client
    shares.
    """

    def __init__(self, *feeds: CarFeed | Subject) -> None:
        self._feeds = feeds
        self._subscriptions = contextlib.ExitStack()
        self._condition = threading.Condition()
        self._pending: dict[str, dict[str, Any]] = {}

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

    def take(self, timeout: float) -> list[dict[str, Any]]:
        with self._condition:
            self._condition.wait_for(lambda: self._pending, timeout)
            messages = list(self._pending.values())
            self._pending.clear()
            return messages

    def _put(self, message: dict[str, Any]) -> None:
        with self._condition:
            self._pending[message["type"]] = message
            self._condition.notify()


CAMERA_PATH = "/camera"
TELEMETRY_PATH = "/telemetry"
DRIVE_PATH = "/drive"


@tracer.start_as_current_span("streamer.server_handler", kind=trace.SpanKind.SERVER)
def server_handler(
    camera: CarFeed,
    telemetry: CarFeed,
    arbiter: CommandArbiter,
    websocket: websockets.sync.server.ServerConnection,
) -> None:
    """WebSocket handler for incoming requests, routed by path."""
    span = trace.get_current_span()
    span.set_attribute("network.protocol.name", "websocket")

    path = websocket.request.path if websocket.request is not None else ""
    span.set_attribute("url.path", path)
    logger.info("Server connection from: %s to %s", websocket.remote_address[0], path)

    try:
        if path == CAMERA_PATH:
            _serve_camera(websocket, camera)
        elif path == TELEMETRY_PATH:
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


def _serve_camera(
    websocket: websockets.sync.server.ServerConnection, camera: CarFeed
) -> None:
    with _Outbox(camera) as outbox:
        _send_until_closed(websocket, outbox)


def _serve_telemetry(
    websocket: websockets.sync.server.ServerConnection,
    telemetry: CarFeed,
    collision_state: Subject,
) -> None:
    with _Outbox(telemetry, collision_state) as outbox:
        _send_until_closed(websocket, outbox)


def _send_until_closed(
    websocket: websockets.sync.server.ServerConnection, outbox: _Outbox
) -> None:
    while websocket.close_code is None:
        for message in outbox.take(timeout=_OUTBOX_POLL_S):
            websocket.send(json.dumps(message))


def camera_message(raw: str | bytes) -> dict[str, Any]:
    """Process one camera frame from the car into a client message."""
    packet: dict[str, Any] = json.loads(raw)
    car_context = extract_trace_context(packet)
    with tracer.start_as_current_span(
        "streamer.handle_camera_frame", context=car_context
    ) as span:
        span.set_attribute("network.protocol.name", "websocket")
        frame = process_frame(camera_frame_jpeg(packet))
        return prepare_camera_frame_packet(frame)


def prepare_camera_frame_packet(frame: bytes) -> dict[str, Any]:
    """Build a stream packet for a processed camera frame with trace context."""
    packet = {"type": "stream", "data": base64.encodebytes(frame).decode("ascii")}
    return inject_trace_context(packet)


def telemetry_message(raw: str | bytes) -> dict[str, Any]:
    """Turn one telemetry packet from the car into a client message."""
    telemetry: dict[str, Any] = json.loads(raw)
    record_telemetry_received()
    car_context = extract_trace_context(telemetry)
    with tracer.start_as_current_span(
        "streamer.handle_telemetry", context=car_context
    ) as span:
        span.set_attribute("network.protocol.name", "websocket")
        return prepare_telemetry_packet(telemetry)


@dataclasses.dataclass(frozen=True)
class StreamerSettings:
    """The streamer's settings, read from the environment."""

    camera_uri: str
    telemetry_uri: str
    drive_uri: str
    observability: ObservabilitySettings

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> Self:
        """Read the settings from `environ`; the car endpoint URIs are required."""
        return cls(
            camera_uri=environ["STREAM_CLIENT_URI"],
            telemetry_uri=environ["TELEMETRY_CLIENT_URI"],
            drive_uri=environ["DRIVE_CLIENT_URI"],
            observability=ObservabilitySettings.from_env(environ),
        )


def prepare_telemetry_packet(telemetry: dict[str, Any]) -> dict[str, Any]:
    """Build a telemetry packet with trace context."""
    packet = {"type": "telemetry", "data": telemetry}
    return inject_trace_context(packet)


def main() -> None:
    """Run the main entry point."""
    settings = StreamerSettings.from_env(os.environ)
    configure_observability("dust-mite-streamer", settings.observability)
    commands = Subject()
    camera = CarFeed(settings.camera_uri, camera_message)
    telemetry = CarFeed(settings.telemetry_uri, telemetry_message)
    arbiter = CommandArbiter(commands, telemetry, CollisionMonitor())
    handler = functools.partial(server_handler, camera, telemetry, arbiter)
    try:
        with (
            send_commands_to_car(settings.drive_uri, commands),
            websockets.sync.server.serve(handler, "0.0.0.0", 8765) as server,  # noqa: S104 - intentional, streamer must accept connections from all interfaces
        ):
            logger.info("Starting server")
            server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    logger.info("Shutting down server")
    server.shutdown()


if __name__ == "__main__":
    main()
