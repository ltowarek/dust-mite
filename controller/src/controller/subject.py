"""Observables, the Subject that fans one out, and a feed shared by reference count."""

import asyncio
import contextlib
import contextvars
import logging
from collections.abc import Awaitable, Callable, Iterator
from typing import Protocol

logger = logging.getLogger(__name__)


class Observable[T](Protocol):
    """Messages that any number of callbacks can subscribe to."""

    def subscription(
        self, callback: Callable[[T], None]
    ) -> contextlib.AbstractContextManager[None]:
        """Call `callback` with each message while the context is open."""
        ...


class Subject[T]:
    """An Observable that can also be published to, delivering to every subscriber.

    `on_active` runs when the first subscriber arrives and `on_idle` after the
    last one leaves: the hooks a RefCount connects and disconnects its upstream
    feed on. It is confined to one thread, the event loop's.
    """

    def __init__(
        self,
        *,
        on_active: Callable[[], None] | None = None,
        on_idle: Callable[[], None] | None = None,
    ) -> None:
        """Initialize the object."""
        self._on_active = on_active
        self._on_idle = on_idle
        self._subscribers: list[Callable[[T], None]] = []

    @contextlib.contextmanager
    def subscription(self, callback: Callable[[T], None]) -> Iterator[None]:
        """Call `callback` with every message published while the context is open."""
        self._subscribe(callback)
        try:
            yield
        finally:
            self._unsubscribe(callback)

    def publish(self, message: T) -> None:
        """Deliver `message` to every current subscriber, logging any that raises."""
        for callback in list(self._subscribers):
            try:
                callback(message)
            except Exception:
                logger.exception("A subscriber failed on a published message")

    def _subscribe(self, callback: Callable[[T], None]) -> None:
        first = not self._subscribers
        self._subscribers.append(callback)
        if first and self._on_active is not None:
            self._on_active()

    def _unsubscribe(self, callback: Callable[[T], None]) -> None:
        self._subscribers.remove(callback)
        if not self._subscribers and self._on_idle is not None:
            self._on_idle()


class RefCountFeed[T]:
    """An Observable that runs one shared `read` only while it has subscribers."""

    def __init__(
        self,
        read: Callable[[Callable[[T], None]], Awaitable[None]],
        tasks: asyncio.TaskGroup,
    ) -> None:
        """Initialize the object; the first subscriber starts `read` in `tasks`."""
        self._read = read
        self._tasks = tasks
        self._task: asyncio.Task[None] | None = None
        # Held while reading, so a new read waits until a cancelled one has finished.
        self._reading = asyncio.Lock()
        self._subject: Subject[T] = Subject(on_active=self._start, on_idle=self._stop)

    def subscription(
        self, callback: Callable[[T], None]
    ) -> contextlib.AbstractContextManager[None]:
        """Call `callback` with each message `read` publishes while subscribed."""
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
        async with self._reading:
            await self._read(self._subject.publish)
