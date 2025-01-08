"""streamer module."""

import datetime
import logging
import os
import time

import cv2
import numpy as np
import websockets.exceptions
import websockets.sync.client
import websockets.sync.server

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

ESP32_ADDRESS = os.environ.get("ESP32_ADDRESS", "ws://192.168.50.66")
CLIENT_URI = ESP32_ADDRESS + "/stream"


def server_handler(websocket: websockets.sync.server.ServerConnection) -> None:
    """WebSocket handler for incoming requests."""
    logger.info("Server connection from: %s", websocket.remote_address[0])
    keep_server_connection = True

    while keep_server_connection:
        try:
            client = websockets.sync.client.connect(CLIENT_URI)
        except (ConnectionRefusedError, OSError, TimeoutError) as e:
            logger.warning("Failed to connect to the client: %s", e)
            time.sleep(1)
            continue

        with client:
            logger.info("Client connected: %s", CLIENT_URI)
            keep_client_connection = True

            while keep_client_connection:
                try:
                    frame: bytes = client.recv(
                        timeout=datetime.timedelta(seconds=1).total_seconds(),
                        decode=False,
                    )  # type: ignore[assignment]  # `recv(decode=False)` returns bytes
                except websockets.exceptions.ConnectionClosed:
                    logger.info("Client connection closed")
                    keep_client_connection = False
                    continue
                except TimeoutError:
                    logger.warning("Client timed out")
                    keep_client_connection = False
                    continue

                frame = process_frame(frame)

                try:
                    websocket.send(frame)
                except websockets.exceptions.ConnectionClosed:
                    logger.info("Server connection closed")
                    keep_client_connection = False
                    keep_server_connection = False
                    continue

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
