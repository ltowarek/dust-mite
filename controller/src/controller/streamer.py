"""streamer module."""

import base64
import contextlib
import datetime
import json
import logging
import os
import queue
import threading
import time
from types import TracebackType
from typing import Any, Self

import cv2
import numpy as np
import websockets.exceptions
import websockets.sync.client
import websockets.sync.server
from opentelemetry import trace

from .tracing import configure_tracing, inject_trace_context

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
                            keep_client_connection = False

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
            timeout=datetime.timedelta(seconds=2).total_seconds(),
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

    def is_frame_available(self) -> bool:
        """Return `True` if there is a frame ready to be received."""
        return self._recv_queue.full()

    def recv(self) -> str | bytes:
        """Receive a frame."""
        return self._recv_queue.get()

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


@tracer.start_as_current_span("streamer.server_handler")
def server_handler(websocket: websockets.sync.server.ServerConnection) -> None:
    """WebSocket handler for incoming requests."""
    span = trace.get_current_span()

    remote_address = websocket.remote_address[0]
    logger.info("Server connection from: %s", remote_address)

    telemetry_client_uri = os.environ["TELEMETRY_CLIENT_URI"]
    controller_client_uri = os.environ["CONTROLLER_CLIENT_URI"]
    stream_client_uri = os.environ["STREAM_CLIENT_URI"]
    span.set_attribute("telemetry_client_uri", telemetry_client_uri)
    span.set_attribute("controller_client_uri", controller_client_uri)
    span.set_attribute("stream_client_uri", stream_client_uri)

    with (
        ClientConnection(stream_client_uri, "r") as stream_client,
        ClientConnection(telemetry_client_uri, "r") as telemetry_client,
        ClientConnection(controller_client_uri, "w") as controller_client,
    ):
        last_camera_frame: bytes = b""
        last_telemetry: dict[str, Any] = {}
        try:
            while True:
                frame = handle_camera_frame(stream_client, websocket)
                if frame is not None:
                    last_camera_frame = frame

                telemetry = handle_telemetry(telemetry_client, websocket)
                if telemetry is not None:
                    last_telemetry = telemetry

                if last_camera_frame and last_telemetry:
                    handle_drive_command(
                        controller_client, last_camera_frame, last_telemetry
                    )
        except websockets.exceptions.ConnectionClosed:
            logger.info("Server connection closed")

    logger.debug("Server handler finished")


def handle_camera_frame(
    stream_client: ClientConnection,
    websocket: websockets.sync.server.ServerConnection,
) -> bytes | None:
    """Receive, process, and forward one camera frame if available.

    Returns the processed frame, or None if no frame was available.
    Raises ConnectionClosed on disconnect.
    """
    if not stream_client.is_frame_available():
        return None
    with tracer.start_as_current_span(
        "streamer.handle_camera_frame",
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        frame: bytes = stream_client.recv()  # type: ignore[assignment]
        frame = process_frame(frame)
        p = prepare_camera_frame_packet(frame)
        try:
            websocket.send(json.dumps(p))
        except websockets.exceptions.ConnectionClosed:
            raise
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            raise
    return frame


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
    return result


@tracer.start_as_current_span("streamer.prepare_camera_frame_packet")
def prepare_camera_frame_packet(frame: bytes) -> dict[str, Any]:
    """Build a stream packet for a processed camera frame with trace context."""
    packet = {"type": "stream", "data": base64.encodebytes(frame).decode("ascii")}
    return inject_trace_context(packet)


def handle_telemetry(
    telemetry_client: ClientConnection,
    websocket: websockets.sync.server.ServerConnection,
) -> dict[str, Any] | None:
    """Receive and forward one telemetry message if available.

    Returns the telemetry dict, or None if no message was available.
    Raises ConnectionClosed on disconnect.
    """
    if not telemetry_client.is_frame_available():
        return None
    with tracer.start_as_current_span(
        "streamer.handle_telemetry",
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        telemetry: dict[str, Any] = json.loads(telemetry_client.recv())
        p = prepare_telemetry_packet(telemetry)
        try:
            websocket.send(json.dumps(p))
        except websockets.exceptions.ConnectionClosed:
            raise
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            raise
    return telemetry


@tracer.start_as_current_span("streamer.prepare_telemetry_packet")
def prepare_telemetry_packet(telemetry: dict[str, Any]) -> dict[str, Any]:
    """Build a telemetry packet with trace context."""
    packet = {"type": "telemetry", "data": telemetry}
    return inject_trace_context(packet)


def handle_drive_command(
    controller_client: ClientConnection,
    frame: bytes,
    telemetry: dict[str, Any],
) -> None:
    """Compute a drive command and send it to the controller if one is produced."""
    # TODO: Make it opt-in, so user can drive as he wants
    command_packet = drive_car(frame, telemetry)
    if command_packet is not None:
        with tracer.start_as_current_span("streamer.handle_drive_command") as span:
            span.set_attribute("distance_ahead", telemetry["distance_ahead"])
            p = prepare_command_packet(command_packet)
            controller_client.send(json.dumps(p))


def drive_car(_frame: bytes, telemetry: dict[str, Any]) -> dict[str, Any] | None:
    """Update car's state based on camera frame and telemetry."""
    # TODO: Get also current state of the car i.e. commands and their values
    # If new state is the same as the old state then
    # there is no need to update the state and send anything
    # Maybe CONTROLLER_CLIENT_URI should send new state after receiving commands

    min_distance = 5
    if telemetry["distance_ahead"] < min_distance:
        # TODO: Integrate with controller.py
        return {"command": 3, "value": None}

    return None


@tracer.start_as_current_span("streamer.prepare_command_packet")
def prepare_command_packet(command: dict[str, Any]) -> dict[str, Any]:
    """Build a drive command packet with trace context."""
    return inject_trace_context(command)


def main() -> None:
    """Run the main entry point."""
    configure_tracing("dust-mite-streamer")
    try:
        with websockets.sync.server.serve(server_handler, "0.0.0.0", 8765) as server:  # noqa: S104 - intentional, streamer must accept connections from all interfaces
            logger.info("Starting server")
            server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    logger.info("Shutting down server")
    server.shutdown()


if __name__ == "__main__":
    main()
