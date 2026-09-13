"""streamer module."""

import base64
import contextlib
import dataclasses
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
                        try:
                            self._send_frame(client)
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

    def _send_frame(self, client: websockets.sync.client.ClientConnection) -> None:
        try:
            send_frame = self._send_queue.get_nowait()
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
    """Reads one car endpoint into `subject`, connected only while it has subscribers.

    Every client subscribes to the same `subject`, so the car serves one
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
        self.subject = Subject(on_active=self._start, on_idle=self._stop)

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
                self.subject.publish(message)


@dataclasses.dataclass(frozen=True)
class CarFeeds:
    """The car's camera and telemetry feeds, shared by every connected client."""

    camera: Subject
    telemetry: Subject

    @classmethod
    def connect(cls, *, stream_uri: str, telemetry_uri: str) -> Self:
        """Create feeds that connect to the car on demand."""
        return cls(
            camera=CarFeed(stream_uri, camera_message).subject,
            telemetry=CarFeed(telemetry_uri, telemetry_message).subject,
        )


class CommandMux:
    """The only path drive commands take to the car.

    Every command goes through `collision_monitor` first. While at least one
    driver is attached, the mux holds the one control connection to the car
    and keeps `collision_monitor` fed from the telemetry feed.
    `collision_state` carries whether the monitor is stopping the car.
    """

    def __init__(
        self,
        control_uri: str,
        telemetry: Subject,
        collision_monitor: CollisionMonitor,
    ) -> None:
        """Initialize the object."""
        self._control_uri = control_uri
        self._telemetry = telemetry
        self._collision_monitor = collision_monitor
        self._lock = threading.Lock()
        self._drivers = 0
        self._attached = contextlib.ExitStack()
        self._control: ClientConnection | None = None
        # Race: only changes are published, so a client that subscribes after
        # the latest change sees no collision state until the next one.
        self.collision_state = Subject()

    @contextlib.contextmanager
    def driver(self) -> Iterator[Callable[[dict[str, Any]], None]]:
        """Attach a driver for the context; yield a function that sends its commands."""
        self._attach()
        try:
            yield self._submit
        finally:
            self._detach()

    def _submit(self, command_packet: dict[str, Any]) -> None:
        with self._lock:
            control = self._control
        assert control is not None

        operator_context = extract_trace_context(command_packet)
        command_packet = self._collision_monitor.filter(command_packet)
        command = Command(command_packet["command"])
        with tracer.start_as_current_span(
            "streamer.handle_drive_command", context=operator_context
        ) as span:
            span.set_attribute("network.protocol.name", "websocket")
            span.set_attribute("command_name", command.name)
            control.send(json.dumps(prepare_command_packet(command_packet)))
            record_command_sent(command)

    def _attach(self) -> None:
        with self._lock:
            self._drivers += 1
            if self._drivers == 1:
                self._control = self._attached.enter_context(
                    ClientConnection(self._control_uri, "w")
                )
                self._attached.enter_context(
                    self._telemetry.subscription(self._on_telemetry)
                )

    def _detach(self) -> None:
        with self._lock:
            self._drivers -= 1
            if self._drivers == 0:
                self._control = None
                self._attached.close()
                if self._collision_monitor.stopping:
                    self._collision_monitor.reset()
                    self._publish_collision_state()

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


class _LatestMessages:
    """Keeps only the newest undelivered message of each type.

    A client that falls behind skips stale camera frames and telemetry instead
    of stalling the feed that every other client shares.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._pending: dict[str, dict[str, Any]] = {}

    def put(self, message: dict[str, Any]) -> None:
        with self._condition:
            self._pending[message["type"]] = message
            self._condition.notify()

    def take(self, timeout: float) -> list[dict[str, Any]]:
        with self._condition:
            self._condition.wait_for(lambda: self._pending, timeout)
            messages = list(self._pending.values())
            self._pending.clear()
            return messages


CAMERA_PATH = "/camera"
TELEMETRY_PATH = "/telemetry"
DRIVE_PATH = "/drive"


@tracer.start_as_current_span("streamer.server_handler", kind=trace.SpanKind.SERVER)
def server_handler(
    feeds: CarFeeds, mux: CommandMux, websocket: websockets.sync.server.ServerConnection
) -> None:
    """WebSocket handler for incoming requests, routed by path."""
    span = trace.get_current_span()
    span.set_attribute("network.protocol.name", "websocket")

    path = websocket.request.path if websocket.request is not None else ""
    span.set_attribute("url.path", path)
    logger.info("Server connection from: %s to %s", websocket.remote_address[0], path)

    try:
        if path == CAMERA_PATH:
            _serve_feed(websocket, feeds.camera)
        elif path == TELEMETRY_PATH:
            _serve_feed(websocket, feeds.telemetry, mux.collision_state)
        elif path == DRIVE_PATH:
            _serve_driver(mux, websocket)
        else:
            websocket.close(CloseCode.POLICY_VIOLATION, f"unknown path: {path}")
    except websockets.exceptions.ConnectionClosed:
        pass
    logger.info("Server connection closed")


def _serve_driver(
    mux: CommandMux, websocket: websockets.sync.server.ServerConnection
) -> None:
    with mux.driver() as submit:
        for message in websocket:
            submit(json.loads(message))


def _serve_feed(
    websocket: websockets.sync.server.ServerConnection, *subjects: Subject
) -> None:
    outbox = _LatestMessages()
    with contextlib.ExitStack() as subscriptions:
        for subject in subjects:
            subscriptions.enter_context(subject.subscription(outbox.put))
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
    feeds = CarFeeds.connect(
        stream_uri=os.environ["STREAM_CLIENT_URI"],
        telemetry_uri=os.environ["TELEMETRY_CLIENT_URI"],
    )
    mux = CommandMux(
        os.environ["CONTROLLER_CLIENT_URI"], feeds.telemetry, CollisionMonitor()
    )
    handler = functools.partial(server_handler, feeds, mux)
    try:
        with websockets.sync.server.serve(handler, "0.0.0.0", 8765) as server:  # noqa: S104 - intentional, streamer must accept connections from all interfaces
            logger.info("Starting server")
            server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    logger.info("Shutting down server")
    server.shutdown()


if __name__ == "__main__":
    main()
