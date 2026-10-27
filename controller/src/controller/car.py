"""The streamer's side of the car: its endpoints and its message format."""

import asyncio
import contextlib
import logging
import threading
from collections.abc import Callable, Coroutine
from typing import Any, Protocol

import websockets.exceptions
from websockets.asyncio.client import ClientConnection

from .reconnecting_connection import stay_connected
from .subject import Subject
from .tracing import inject_trace_context
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


# A provider: each call returns a new connection, not yet open.
type ConnectionProvider[T] = Callable[
    [], contextlib.AbstractContextManager[Receiver[T]]
]


class CarFeed[M]:
    """A RefCount over one car endpoint: connected only while it has subscribers.

    Every client subscribes to the same feed, so the car serves one
    connection per endpoint no matter how many clients are connected.
    """

    def __init__[T](
        self,
        connection_provider: ConnectionProvider[T],
        to_message: Callable[[T], M],
    ) -> None:
        """Initialize the object; each first subscriber calls `connection_provider`."""

        def read_until_stopped() -> None:
            with connection_provider() as client:
                while not self._stop_event.is_set():
                    try:
                        raw = client.recv(timeout=_FEED_STOP_CHECK_S)
                    except TimeoutError:
                        continue
                    try:
                        message = to_message(raw)
                    except Exception:
                        logger.exception("Dropping an unreadable message from the car")
                        continue
                    self._subject.publish(message)

        self._read_until_stopped = read_until_stopped
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._subject: Subject[M] = Subject(on_active=self._start, on_idle=self._stop)

    def subscription(
        self, callback: Callable[[M], None]
    ) -> contextlib.AbstractContextManager[None]:
        """Call `callback` with each message from the car while the context is open."""
        return self._subject.subscription(callback)

    def _start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._read_until_stopped)
        self._thread.start()

    def _stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()


# Reads one car Endpoint until cancelled, calling the given function with each message.
type CarReader[M] = Callable[[Callable[[M], None]], Coroutine[Any, Any, None]]


class AsyncCarFeed[M]:
    """A RefCount over one car endpoint, read by a task on the event loop.

    The first subscriber starts a task in `tasks` that runs `read`; the last
    one cancels it. Every client subscribes to the same feed, so the car
    serves one connection per endpoint no matter how many clients are connected.
    """

    def __init__(self, read: CarReader[M], tasks: asyncio.TaskGroup) -> None:
        """Initialize the object."""
        self._read = read
        self._tasks = tasks
        self._task: asyncio.Task[None] | None = None
        self._subject: Subject[M] = Subject(on_active=self._start, on_idle=self._stop)

    def subscription(
        self, callback: Callable[[M], None]
    ) -> contextlib.AbstractContextManager[None]:
        """Call `callback` with each message from the car while the context is open."""
        return self._subject.subscription(callback)

    def _start(self) -> None:
        self._task = self._tasks.create_task(self._read_after(self._task))

    def _stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def _read_after(self, previous: asyncio.Task[None] | None) -> None:
        # The car refuses a second connection to one Endpoint as busy.
        if previous is not None:
            await asyncio.wait([previous])
        await self._read(self._subject.publish)


async def read_car_websocket[M](
    uri: str,
    to_message: Callable[[str | bytes], M],
    publish: Callable[[M], None],
) -> None:
    """Publish each message from the car's WebSocket endpoint `uri` until cancelled."""

    async def publish_all(connection: ClientConnection) -> None:
        with contextlib.suppress(websockets.exceptions.ConnectionClosed):
            async for raw in connection:
                try:
                    message = to_message(raw)
                except Exception:
                    logger.exception("Dropping an unreadable message from the car")
                    continue
                publish(message)

    await stay_connected(uri, publish_all)


def prepare_drive_command(command: WebSocketMessage) -> WebSocketMessage:
    """Build a Drive command for the car with trace context."""
    return inject_trace_context(command)
