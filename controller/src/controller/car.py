"""The streamer's side of the car: its endpoints and its packet format."""

import base64
import contextlib
import json
import logging
import threading
from collections.abc import Callable, Iterator

from .packet import Packet
from .subject import Subject
from .tracing import inject_trace_context
from .websocket_client import ClientConnection

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# How long a car feed waits for a message from the car before rechecking
# whether it should stop.
_FEED_STOP_CHECK_S = 0.2


class CarFeed:
    """Reads one car endpoint, connected only while it has subscribers.

    Every client subscribes to the same feed, so the car serves one
    connection per endpoint no matter how many clients are connected.
    """

    def __init__(self, uri: str, to_packet: Callable[[str | bytes], Packet]) -> None:
        """Initialize the object."""
        self._uri = uri
        self._to_packet = to_packet
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._subject: Subject[Packet] = Subject(
            on_active=self._start, on_idle=self._stop
        )

    def subscription(
        self, callback: Callable[[Packet], None]
    ) -> contextlib.AbstractContextManager[None]:
        """Call `callback` with each packet from the car while the context is open."""
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
                    packet = self._to_packet(raw)
                except Exception:
                    logger.exception("Dropping unreadable message from %s", self._uri)
                    continue
                self._subject.publish(packet)


@contextlib.contextmanager
def send_commands_to_car(uri: str, commands: Subject[Packet]) -> Iterator[None]:
    """Send each command published on `commands` to the car while the context is open.

    The car's one Drive endpoint connection stays open for the whole context, so
    every driver's commands share it.
    """
    with (
        ClientConnection(uri, "w") as connection,
        commands.subscription(lambda command: connection.send(json.dumps(command))),
    ):
        yield


def camera_frame_jpeg(packet: Packet) -> bytes:
    """Return the JPEG carried by a camera packet from the car."""
    return base64.b64decode(packet["data"])


def prepare_command_packet(command: Packet) -> Packet:
    """Build a drive command packet with trace context."""
    return inject_trace_context(command)
