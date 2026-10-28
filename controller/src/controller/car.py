"""The streamer's side of the car: its endpoints and its message format."""

import asyncio
import contextlib
import contextvars
from collections.abc import Awaitable, Callable

from .subject import Subject
from .tracing import inject_trace_context
from .websocket_message import WebSocketMessage


class CarFeed[M]:
    """A RefCount over one car endpoint: connected only while it has subscribers.

    Every client subscribes to the same feed, so the car serves one
    connection per endpoint no matter how many clients are connected.
    """

    def __init__(
        self,
        read: Callable[[Callable[[M], None]], Awaitable[None]],
        tasks: asyncio.TaskGroup,
    ) -> None:
        """Initialize the object; `read` publishes to every subscriber until cancelled.

        The first subscriber starts it in `tasks` and the last one cancels it.
        """
        self._read = read
        self._tasks = tasks
        self._task: asyncio.Task[None] | None = None
        # Held while reading, so a new read waits until a cancelled one has closed.
        self._connection = asyncio.Lock()
        self._subject: Subject[M] = Subject(on_active=self._start, on_idle=self._stop)

    def subscription(
        self, callback: Callable[[M], None]
    ) -> contextlib.AbstractContextManager[None]:
        """Call `callback` with each message from the car while the context is open."""
        return self._subject.subscription(callback)

    def _start(self) -> None:
        # A fresh context, so the feed does not run inside its first subscriber's span.
        self._task = self._tasks.create_task(
            self._read_alone(), context=contextvars.Context()
        )

    def _stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def _read_alone(self) -> None:
        async with self._connection:
            await self._read(self._subject.publish)


def prepare_drive_command(command: WebSocketMessage) -> WebSocketMessage:
    """Build a Drive command for the car with trace context."""
    return inject_trace_context(command)
