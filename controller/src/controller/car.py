"""The streamer's side of the car: its endpoints and its message format."""

import contextlib
import json
import logging
import threading
from collections.abc import Callable, Iterator
from typing import Protocol

from .subject import Subject
from .tracing import inject_trace_context
from .websocket_client import ClientConnection
from .websocket_message import WebSocketMessage

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# How long a car feed waits for a message from the car before rechecking
# whether it should stop.
_FEED_STOP_CHECK_S = 0.2


class Receiver[T](Protocol):
    """A connection to a car endpoint that hands over what the car sent."""

    def recv(self, timeout: float) -> T:
        """Return the next item, raising `TimeoutError` if none arrives in `timeout`."""
        ...


class CarFeed[T]:
    """Reads one car endpoint, connected only while it has subscribers.

    Every client subscribes to the same feed, so the car serves one
    connection per endpoint no matter how many clients are connected.
    """

    def __init__(
        self,
        connect: Callable[[], contextlib.AbstractContextManager[Receiver[T]]],
        to_message: Callable[[T], WebSocketMessage],
    ) -> None:
        """Initialize the object; `connect` opens a connection to the endpoint."""
        self._connect = connect
        self._to_message = to_message
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._subject: Subject[WebSocketMessage] = Subject(
            on_active=self._start, on_idle=self._stop
        )

    def subscription(
        self, callback: Callable[[WebSocketMessage], None]
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
        with self._connect() as client:
            while not self._stop_event.is_set():
                try:
                    raw = client.recv(timeout=_FEED_STOP_CHECK_S)
                except TimeoutError:
                    continue
                try:
                    message = self._to_message(raw)
                except Exception:
                    logger.exception("Dropping an unreadable message from the car")
                    continue
                self._subject.publish(message)


@contextlib.contextmanager
def send_commands_to_car(
    uri: str, commands: Subject[WebSocketMessage]
) -> Iterator[None]:
    """Send each command published on `commands` to the car while the context is open.

    The car's one Drive endpoint connection stays open for the whole context, so
    every driver's commands share it.
    """
    with (
        ClientConnection(uri, "w") as connection,
        commands.subscription(lambda command: connection.send(json.dumps(command))),
    ):
        yield


def prepare_drive_command(command: WebSocketMessage) -> WebSocketMessage:
    """Build a Drive command for the car with trace context."""
    return inject_trace_context(command)
