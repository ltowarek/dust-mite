"""streamer module."""

import base64
import datetime
import json
import logging
import os
import queue
import threading
import time
from types import TracebackType

import cv2
import numpy as np
import websockets.exceptions
import websockets.sync.client
import websockets.sync.server

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

ESP32_ADDRESS = os.environ.get("ESP32_ADDRESS", "ws://192.168.50.66")
STREAM_CLIENT_URI = ESP32_ADDRESS + "/stream"
TELEMETRY_CLIENT_URI = ESP32_ADDRESS + "/telemetry"


class ClientConnection:
    """Wrapper around Websocket client connection.

    Mostly needed to handle/receive all messages from the client.
    Even in case when receiver can't process all messages in time.

    All messages that can't be processed will be discarded.
    """

    def __init__(self, uri: str) -> None:
        """Initialize the object."""
        self._uri = uri
        self._worker = threading.Thread(target=self._worker_main)
        self._stop_event = threading.Event()
        self._queue: queue.Queue[str | bytes] = queue.Queue(1)

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

                while not self._stop_event.is_set():
                    try:
                        frame = client.recv(
                            timeout=datetime.timedelta(seconds=2).total_seconds(),
                        )
                    except websockets.exceptions.ConnectionClosed:
                        logger.info("%s connection closed", self._uri)
                        break
                    except TimeoutError:
                        logger.warning("%s timed out", self._uri)
                        break

                    try:
                        self._queue.put_nowait(frame)
                    except queue.Full:
                        continue
        logger.debug("Client worker finished")

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
        return self._queue.full()

    def recv(self) -> str | bytes:
        """Receive a frame."""
        return self._queue.get()

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

    with (
        ClientConnection(STREAM_CLIENT_URI) as stream_client,
        ClientConnection(TELEMETRY_CLIENT_URI) as telemetry_client,
    ):
        while True:
            if telemetry_client.is_frame_available():
                telemetry = json.loads(telemetry_client.recv())
                packet = {
                    "type": "telemetry",
                    "data": telemetry,
                }
                try:
                    websocket.send(json.dumps(packet))
                except websockets.exceptions.ConnectionClosed:
                    logger.info("Server connection closed")
                    break

            if stream_client.is_frame_available():
                camera_frame = stream_client.recv()
                assert isinstance(camera_frame, bytes)
                camera_frame = process_frame(camera_frame)
                packet = {
                    "type": "stream",
                    "data": base64.encodebytes(camera_frame).decode("ascii"),
                }
                try:
                    websocket.send(json.dumps(packet))
                except websockets.exceptions.ConnectionClosed:
                    logger.info("Server connection closed")
                    break

    logger.debug("Server handler finished")


def process_frame(frame: bytes) -> bytes:
    """Process camera frame."""
    arr = np.frombuffer(frame, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    return cv2.imencode(".jpg", img)[1].tobytes()


if __name__ == "__main__":
    try:
        with websockets.sync.server.serve(server_handler, "localhost", 8765) as server:
            logger.info("Starting server")
            server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    logger.info("Shutting down server")
    server.shutdown()
