"""Fan-out on the event loop, and Outboxes sending it on to one peer."""

import abc
import asyncio
import collections
import contextlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from types import TracebackType
from typing import Any, Self, override

import websockets.exceptions
from websockets.asyncio.connection import Connection

from .websocket_message import WebSocketMessage


class Broadcast[M]:
    """Messages published on the event loop to every Outbox or Inbox open on it.

    It is confined to the event loop, so it takes no lock.
    """

    def __init__(self) -> None:
        """Initialize the object."""
        self._subscriptions: list[_Subscription[M]] = []

    def publish(self, message: M) -> None:
        """Hand `message` to every open Outbox or Inbox."""
        for subscription in self._subscriptions:
            subscription.put(self, message)

    def add(self, subscription: "_Subscription[M]") -> None:
        """Hand each message published from now on to `subscription`."""
        self._subscriptions.append(subscription)

    def remove(self, subscription: "_Subscription[M]") -> None:
        """Stop handing messages to `subscription`."""
        self._subscriptions.remove(subscription)


class _Subscription[M](abc.ABC):
    """Messages from some Broadcasts, received with `async for` while open.

    It opens only once. Once closed, iteration ends after the messages
    received while it was open.
    """

    def __init__(self, *sources: Broadcast[M]) -> None:
        self._sources = sources
        self._ready = asyncio.Event()
        self._opened = False
        self._closed = False

    async def __aenter__(self) -> Self:
        """Receive from the sources; raise `RuntimeError` if opened before."""
        if self._opened:
            msg = "an Outbox or Inbox opens only once"
            raise RuntimeError(msg)
        self._opened = True
        for source in self._sources:
            source.add(self)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: TracebackType | None,
    ) -> None:
        """Stop receiving from the sources."""
        for source in self._sources:
            source.remove(self)
        self._closed = True
        self._ready.set()

    def __aiter__(self) -> Self:
        """Iterate over the kept messages."""
        return self

    async def __anext__(self) -> M:
        """Wait for a message, then return the one kept longest."""
        while not self._has_pending():
            if self._closed:
                raise StopAsyncIteration
            self._ready.clear()
            await self._ready.wait()
        return self._take()

    def put(self, source: Broadcast[M], message: M) -> None:
        """Keep `message`, published on `source`."""
        self._keep(source, message)
        self._ready.set()

    @abc.abstractmethod
    def _keep(self, source: Broadcast[M], message: M) -> None: ...

    @abc.abstractmethod
    def _take(self) -> M: ...

    @abc.abstractmethod
    def _has_pending(self) -> bool: ...


class Outbox[M](_Subscription[M]):
    """One peer's view of some Broadcasts, keeping the newest message of each.

    A peer that falls behind skips stale messages instead of stalling the
    Broadcasts that every other peer shares.
    """

    def __init__(self, *sources: Broadcast[M]) -> None:
        """Initialize the object."""
        super().__init__(*sources)
        self._newest: collections.OrderedDict[Broadcast[M], M] = (
            collections.OrderedDict()
        )

    @override
    def _keep(self, source: Broadcast[M], message: M) -> None:
        self._newest[source] = message

    @override
    def _take(self) -> M:
        _, message = self._newest.popitem(last=False)
        return message

    @override
    def _has_pending(self) -> bool:
        return bool(self._newest)


class Inbox[M](_Subscription[M]):
    """Every message of some Broadcasts, in the order they were published."""

    def __init__(self, *sources: Broadcast[M]) -> None:
        """Initialize the object."""
        super().__init__(*sources)
        self._messages: collections.deque[M] = collections.deque()

    @override
    def _keep(self, source: Broadcast[M], message: M) -> None:
        self._messages.append(message)

    @override
    def _take(self) -> M:
        return self._messages.popleft()

    @override
    def _has_pending(self) -> bool:
        return bool(self._messages)


class RefCountFeed[M]:
    """A Broadcast fed by one shared `read` that runs only while someone watches."""

    def __init__(
        self, read: Callable[[Callable[[M], None]], Coroutine[Any, Any, None]]
    ) -> None:
        """Initialize the object; `supervise` runs `read`."""
        self._read = read
        self._broadcast: Broadcast[M] = Broadcast()
        self._watchers = 0
        self._watchers_changed = asyncio.Condition()

    @contextlib.asynccontextmanager
    async def watching(self) -> AsyncIterator[Outbox[M]]:
        """Receive the feed through an Outbox while the context is open."""
        async with Outbox(self._broadcast) as outbox:
            await self._add_watchers(1)
            try:
                yield outbox
            finally:
                await self._add_watchers(-1)

    async def supervise(self) -> None:
        """Run `read` while anyone watches, until cancelled; its errors propagate."""
        while True:
            await self._wait_until(lambda: self._watchers > 0)
            async with asyncio.TaskGroup() as tasks:
                reader = tasks.create_task(self._read(self._broadcast.publish))
                await self._wait_until(lambda: self._watchers == 0)
                reader.cancel()

    async def _add_watchers(self, count: int) -> None:
        async with self._watchers_changed:
            self._watchers += count
            self._watchers_changed.notify_all()

    async def _wait_until(self, predicate: Callable[[], bool]) -> None:
        async with self._watchers_changed:
            await self._watchers_changed.wait_for(predicate)


async def send_until_closed[M](
    connection: Connection,
    send: Callable[[Connection, M], Awaitable[None]],
    *sources: Broadcast[M],
) -> None:
    """Pass each source's newest message to `send` while `connection` is open."""
    # Sources may go quiet, so the close is awaited on its own.
    async with Outbox(*sources) as outbox, asyncio.TaskGroup() as tasks:
        sender = tasks.create_task(_send_all(connection, send, outbox))
        await connection.wait_closed()
        sender.cancel()


async def send_json(connection: Connection, message: WebSocketMessage) -> None:
    """Send `message` to `connection` as JSON."""
    await connection.send(json.dumps(message))


async def _send_all[M](
    connection: Connection,
    send: Callable[[Connection, M], Awaitable[None]],
    outbox: Outbox[M],
) -> None:
    with contextlib.suppress(websockets.exceptions.ConnectionClosed):
        async for message in outbox:
            await send(connection, message)
