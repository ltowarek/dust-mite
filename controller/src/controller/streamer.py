"""streamer module."""

import base64
import contextlib
import datetime
import functools
import json
import logging
import os
import queue
import threading
import time
from collections.abc import Callable, Iterator
from types import TracebackType
from typing import Any, Self

import cv2
import numpy as np
import websockets.exceptions
import websockets.sync.client
import websockets.sync.server
from opentelemetry import trace
from websockets.frames import CloseCode

from .collision_monitor import CollisionMonitor
from .command import Command
from .logging import configure_logging
from .metrics import (
    configure_metrics,
    record_command_sent,
    record_frame,
    record_telemetry_received,
)
from .profiling import configure_profiling
from .subject import Subject
from .tracing import configure_tracing, extract_trace_context, inject_trace_context

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

tracer = trace.get_tracer(__name__)

# How long a write-only connection waits for something to send before
# rechecking whether it should stop.
_SEND_WAIT_S = 0.2


class ClientConnection:
    """Wrapper around Websocket client connection.

    Mostly needed to handle/receive all messages from the client.
    Even in case when receiver can't process all messages in time.

    All messages that can't be processed will be discarded.
    """

    def __init__(self, uri: str, mode: str) -> None:
        """Initialize the object."""
        self._uri = uri
        self._mode = mode
        self._worker = threading.Thread(target=self._worker_main)
        self._stop_event = threading.Event()
        self._recv_queue: queue.Queue[str | bytes] = queue.Queue(1)
        self._send_queue: queue.Queue[str | bytes] = queue.Queue(1)

    def _worker_main(self) -> None:
        while not self._stop_event.is_set():
            try:
                client = websockets.sync.client.connect(self._uri)
            except (ConnectionRefusedError, OSError, TimeoutError) as e:
                logger.warning("Failed to connect to the client: %s", e)
                time.sleep(1)
                continue

            with client:
                logger.info("Client connected: %s", self._uri)
                keep_client_connection = True

                while not self._stop_event.is_set() and keep_client_connection:
                    # TODO: Rewrite with asyncio
                    # So "w" and "r" can be supported at the same time
                    if "w" in self._mode:
                        # A read-write connection must not wait here, or it
                        # would delay reading; a write-only one would spin.
                        send_wait_s = 0 if "r" in self._mode else _SEND_WAIT_S
                        try:
                            self._send_frame(client, send_wait_s)
                        except websockets.exceptions.ConnectionClosed:
                            logger.info("%s connection closed", self._uri)
                            keep_client_connection = False

                    if "r" in self._mode:
                        try:
                            self._recv_frame(client)
                        except websockets.exceptions.ConnectionClosedOK:
                            logger.info("%s connection closed", self._uri)
                            keep_client_connection = False
                        except websockets.exceptions.ConnectionClosedError as e:
                            logger.info(
                                "%s connection closed - error: %s", self._uri, e
                            )
                            keep_client_connection = False
                        except TimeoutError:
                            logger.warning("%s timed out", self._uri)
                            continue

        logger.debug("Client worker finished")

    def _send_frame(
        self, client: websockets.sync.client.ClientConnection, wait_s: float
    ) -> None:
        try:
            send_frame = self._send_queue.get(timeout=wait_s)
        except queue.Empty:
            return

        try:
            client.send(send_frame)
        finally:
            self._send_queue.task_done()

    def _recv_frame(self, client: websockets.sync.client.ClientConnection) -> None:
        recv_frame = client.recv(
            timeout=datetime.timedelta(seconds=5).total_seconds(),
        )
        with contextlib.suppress(queue.Full):
            self._recv_queue.put_nowait(recv_frame)

    def connect(self) -> None:
        """Connect to the client."""
        logger.debug("Connecting to %s", self._uri)
        self._worker.start()

    def close(self) -> None:
        """Connect the connection."""
        logger.debug("Closing %s connection", self._uri)
        self._stop_event.set()
        self._worker.join()

    def recv(self, timeout: float | None = None) -> str | bytes:
        """Receive a frame, raising `TimeoutError` if none arrives in `timeout`."""
        try:
            return self._recv_queue.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError from None

    def send(self, frame: str | bytes) -> None:
        """Send a frame."""
        self._send_queue.put(frame)

    def __enter__(self) -> Self:
        """Open a connection in a context manager."""
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: TracebackType | None,
    ) -> None:
        """Close the connection in a context manager."""
        self.close()


# How long an idle client handler waits for a message before rechecking
# whether its client has disconnected.
_OUTBOX_POLL_S = 0.2

# How long a car feed waits for a message from the car before rechecking
# whether it should stop.
_FEED_STOP_CHECK_S = 0.2


class CarFeed:
    """Reads one car endpoint, connected only while it has subscribers.

    Every client subscribes to the same feed, so the car serves one
    connection per endpoint no matter how many clients are connected.
    """

    def __init__(
        self, uri: str, to_message: Callable[[str | bytes], dict[str, Any]]
    ) -> None:
        """Initialize the object."""
        self._uri = uri
        self._to_message = to_message
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._subject = Subject(on_active=self._start, on_idle=self._stop)

    def subscription(
        self, callback: Callable[[Any], None]
    ) -> contextlib.AbstractContextManager[None]:
        """Call `callback` with each message from the car while the context is open."""
        return self._subject.subscription(callback)

    def _start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run)
        self._thread.start()

    def _stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()

    def _run(self) -> None:
        with ClientConnection(self._uri, "r") as client:
            while not self._stop_event.is_set():
                try:
                    raw = client.recv(timeout=_FEED_STOP_CHECK_S)
                except TimeoutError:
                    continue
                try:
                    message = self._to_message(raw)
                except Exception:
                    logger.exception("Dropping unreadable message from %s", self._uri)
                    continue
                self._subject.publish(message)


@contextlib.contextmanager
def send_commands_to_car(uri: str, commands: Subject) -> Iterator[None]:
    """Send each command published on `commands` to the car while the context is open.

    The car's one control connection stays open for the whole context, so
    every driver's commands share it.
    """
    with (
        ClientConnection(uri, "w") as connection,
        commands.subscription(lambda command: connection.send(json.dumps(command))),
    ):
        yield


class DriverAlreadyConnectedError(Exception):
    """Another driver already holds the CommandArbiter."""


class CommandArbiter:
    """Decides which drive commands reach the car.

    One driver at a time may claim it; another is refused until the first
    releases it. Every command goes through `collision_monitor` first and is
    then published on `commands`. While a driver holds the claim, the arbiter
    keeps `collision_monitor` fed from the telemetry feed.
    `collision_state` carries whether the monitor is stopping the car.
    """

    def __init__(
        self,
        commands: Subject,
        telemetry: CarFeed,
        collision_monitor: CollisionMonitor,
    ) -> None:
        """Initialize the object."""
        self._commands = commands
        self._telemetry = telemetry
        self._collision_monitor = collision_monitor
        self._lock = threading.Lock()
        self._claimed = False
        # Race: only changes are published, so a client that subscribes after
        # the latest change sees no collision state until the next one.
        self.collision_state = Subject()

    @contextlib.contextmanager
    def claim(self) -> Iterator[Callable[[dict[str, Any]], None]]:
        """Hold the arbiter for the context; yield a function that sends commands.

        Raises `DriverAlreadyConnectedError` if another driver holds it.
        """
        with self._lock:
            if self._claimed:
                raise DriverAlreadyConnectedError
            self._claimed = True
        try:
            with self._telemetry.subscription(self._on_telemetry):
                yield self._submit
        finally:
            if self._collision_monitor.stopping:
                self._collision_monitor.reset()
                self._publish_collision_state()
            with self._lock:
                self._claimed = False

    def _submit(self, command_packet: dict[str, Any]) -> None:
        operator_context = extract_trace_context(command_packet)
        command_packet = self._collision_monitor.filter(command_packet)
        command = Command(command_packet["command"])
        with tracer.start_as_current_span(
            "streamer.handle_drive_command", context=operator_context
        ) as span:
            span.set_attribute("network.protocol.name", "websocket")
            span.set_attribute("command_name", command.name)
            self._commands.publish(prepare_command_packet(command_packet))
            record_command_sent(command)

    def _on_telemetry(self, message: dict[str, Any]) -> None:
        if self._collision_monitor.update(message["data"]["distance_ahead"]):
            self._publish_collision_state()

    def _publish_collision_state(self) -> None:
        self.collision_state.publish(
            inject_trace_context(
                {
                    "type": "collision_monitor",
                    "stopping": self._collision_monitor.stopping,
                }
            )
        )


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

DRIVER_ALREADY_CONNECTED = "another driver is connected"


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
    except DriverAlreadyConnectedError:
        websocket.close(CloseCode.TRY_AGAIN_LATER, DRIVER_ALREADY_CONNECTED)


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
    """Decode and process one camera frame from the car into a client message."""
    packet: dict[str, Any] = json.loads(raw)
    car_context = extract_trace_context(packet)
    with tracer.start_as_current_span(
        "streamer.handle_camera_frame", context=car_context
    ) as span:
        span.set_attribute("network.protocol.name", "websocket")
        frame = process_frame(base64.b64decode(packet["data"]))
        return prepare_camera_frame_packet(frame)


@tracer.start_as_current_span("streamer.process_frame")
def process_frame(frame: bytes) -> bytes:
    """Process camera frame."""
    span = trace.get_current_span()
    span.set_attribute("input_size_bytes", len(frame))

    arr = np.frombuffer(frame, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    result = cv2.imencode(".jpg", img)[1].tobytes()

    span.set_attribute("output_size_bytes", len(result))
    record_frame()
    return result


def prepare_camera_frame_packet(frame: bytes) -> dict[str, Any]:
    """Build a stream packet for a processed camera frame with trace context."""
    packet = {"type": "stream", "data": base64.encodebytes(frame).decode("ascii")}
    return inject_trace_context(packet)


def telemetry_message(raw: str | bytes) -> dict[str, Any]:
    """Decode one telemetry packet from the car into a client message."""
    telemetry: dict[str, Any] = json.loads(raw)
    record_telemetry_received()
    car_context = extract_trace_context(telemetry)
    with tracer.start_as_current_span(
        "streamer.handle_telemetry", context=car_context
    ) as span:
        span.set_attribute("network.protocol.name", "websocket")
        return prepare_telemetry_packet(telemetry)


def prepare_telemetry_packet(telemetry: dict[str, Any]) -> dict[str, Any]:
    """Build a telemetry packet with trace context."""
    packet = {"type": "telemetry", "data": telemetry}
    return inject_trace_context(packet)


def prepare_command_packet(command: dict[str, Any]) -> dict[str, Any]:
    """Build a drive command packet with trace context."""
    return inject_trace_context(command)


def main() -> None:
    """Run the main entry point."""
    configure_tracing("dust-mite-streamer")
    configure_logging("dust-mite-streamer")
    configure_metrics("dust-mite-streamer")
    configure_profiling("dust-mite-streamer")
    commands = Subject()
    camera = CarFeed(os.environ["STREAM_CLIENT_URI"], camera_message)
    telemetry = CarFeed(os.environ["TELEMETRY_CLIENT_URI"], telemetry_message)
    arbiter = CommandArbiter(commands, telemetry, CollisionMonitor())
    handler = functools.partial(server_handler, camera, telemetry, arbiter)
    try:
        with (
            send_commands_to_car(os.environ["CONTROLLER_CLIENT_URI"], commands),
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
