"""A websocket client that keeps reconnecting and drops what it can't keep up with."""

import contextlib
import datetime
import logging
import queue
import threading
import time
from types import TracebackType
from typing import Self

import websockets.exceptions
import websockets.sync.client

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# How long a write-only connection waits for something to send before
# rechecking whether it should stop.
_SEND_WAIT_S = 0.2


class WebSocketClient:
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
                client = websockets.sync.client.connect(self._uri, proxy=None)
            except (
                ConnectionRefusedError,
                OSError,
                TimeoutError,
                websockets.exceptions.InvalidStatus,
            ) as e:
                logger.warning("Failed to connect to the client: %s", e)
                time.sleep(1)
                continue

            with client:
                logger.info("Client connected: %s", self._uri)
                keep_client_connection = True

                while not self._stop_event.is_set() and keep_client_connection:
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
