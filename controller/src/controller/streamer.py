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
from typing import Any

import cv2
import numpy as np
import websockets.exceptions
import websockets.sync.client
import websockets.sync.server

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


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

    def __enter__(self) -> "ClientConnection":
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


def server_handler(websocket: websockets.sync.server.ServerConnection) -> None:
    """WebSocket handler for incoming requests."""
    logger.info("Server connection from: %s", websocket.remote_address[0])

    telemetry_client_uri = os.environ["TELEMETRY_CLIENT_URI"]
    controller_client_uri = os.environ["CONTROLLER_CLIENT_URI"]
    stream_client_uri = os.environ["STREAM_CLIENT_URI"]

    with (
        ClientConnection(stream_client_uri, "r") as stream_client,
        ClientConnection(telemetry_client_uri, "r") as telemetry_client,
        ClientConnection(controller_client_uri, "w") as controller_client,
    ):
        camera_frame: bytes = b""
        telemetry: dict[str, Any] = {}
        keep_server_connection = True
        while keep_server_connection:
            packets: list[dict[str, Any]] = []
            if stream_client.is_frame_available():
                camera_frame = stream_client.recv()  # type: ignore[assignment]
                camera_frame = process_frame(camera_frame)
                packets.append(
                    {
                        "type": "stream",
                        "data": base64.encodebytes(camera_frame).decode("ascii"),
                    }
                )

            if telemetry_client.is_frame_available():
                telemetry = json.loads(telemetry_client.recv())
                packets.append(
                    {
                        "type": "telemetry",
                        "data": telemetry,
                    }
                )

            # TODO: Make it opt-in, so user can drive as he wants
            if packets:
                command_packet = drive_car(camera_frame, telemetry)
                if command_packet is not None:
                    controller_client.send(json.dumps(command_packet))

            for packet in packets:
                try:
                    websocket.send(json.dumps(packet))
                except websockets.exceptions.ConnectionClosed:
                    logger.info("Server connection closed")
                    keep_server_connection = False

    logger.debug("Server handler finished")


def process_frame(frame: bytes) -> bytes:
    """Process camera frame."""
    arr = np.frombuffer(frame, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    return cv2.imencode(".jpg", img)[1].tobytes()


def drive_car(_frame: bytes, telemetry: dict[str, Any]) -> dict[str, Any] | None:
    """Update car's state based on camera frame and telemetry."""
    if not telemetry:
        return None

    # TODO: Get also current state of the car i.e. commands and their values
    # If new state is the same as the old state then
    # there is no need to update the state and send anything
    # Maybe CONTROLLER_CLIENT_URI should send new state after receiving commands

    min_distance = 5
    if telemetry["distance_ahead"] < min_distance:
        # TODO: Integrate with controller.py
        return {
            "command": 3,
            "value": None,
        }
    return None


if __name__ == "__main__":
    try:
        with websockets.sync.server.serve(server_handler, "localhost", 8765) as server:
            logger.info("Starting server")
            server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    logger.info("Shutting down server")
    server.shutdown()
