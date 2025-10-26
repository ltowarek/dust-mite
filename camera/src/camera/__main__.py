import io
import time
import logging
from websockets.exceptions import ConnectionClosed
from websockets.sync.server import ServerConnection, serve

from picamera2 import Picamera2


logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def server_handler(websocket: ServerConnection) -> None:
    logger.info("Server connection from: %s", websocket.remote_address[0])

    max_size = 2 ** 20
    keep_server_connection = True
    while keep_server_connection:
        data = io.BytesIO()
        picam2.capture_file(data, format="jpeg")
        data.seek(0)

        fragments: list[bytes] = []
        while camera_frame := data.read(max_size):
            fragments.append(camera_frame)
        if not fragments:
            logger.debug("No camera frame available")
            continue

        try:
            websocket.send(fragments)
        except ConnectionClosed:
            logger.info("Server connection closed")
            keep_server_connection = False

    logger.debug("Server handler finished")


if __name__ == "__main__":
    picam2 = Picamera2()
    picam2.start()
    time.sleep(1)
    try:
        with serve(server_handler, "0.0.0.0", 8765) as server:
            logger.info("Starting server")
            server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    logger.info("Shutting down server")
    server.shutdown()
