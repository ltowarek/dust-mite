"""Outboxes: the newest message of each source, sent on to one WebSocket peer."""

import asyncio
import contextlib
import functools
import json
from collections.abc import Callable
from types import TracebackType
from typing import Self

import websockets.exceptions
from websockets.asyncio.connection import Connection

from .subject import Observable
from .websocket_message import WebSocketMessage


def subscribe_all[M](
    sources: tuple[Observable[M], ...], put: Callable[[int, M], None]
) -> contextlib.ExitStack:
    """Subscribe `put` to each source, by its slot; unsubscribe all on any failure."""
    with contextlib.ExitStack() as subscriptions:
        for slot, source in enumerate(sources):
            subscriptions.enter_context(
                source.subscription(functools.partial(put, slot))
            )
        return subscriptions.pop_all()


class Outbox[M]:
    """One peer's view of some sources, keeping the newest message of each.

    Use as a context manager: it subscribes to `sources` on entry and
    unsubscribes on exit. A peer that falls behind skips stale messages
    instead of stalling the sources that every other peer shares.
    """

    def __init__(self, *sources: Observable[M]) -> None:
        """Initialize the object."""
        self._sources = sources
        self._subscriptions = contextlib.ExitStack()
        self._ready = asyncio.Event()
        self._pending: dict[int, M] = {}

    def __enter__(self) -> Self:
        """Subscribe to the sources."""
        self._subscriptions = subscribe_all(self._sources, self._put)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: TracebackType | None,
    ) -> None:
        """Unsubscribe from the sources."""
        self._subscriptions.close()

    async def take(self) -> list[M]:
        """Wait for at least one message, then return the newest of each source."""
        await self._ready.wait()
        self._ready.clear()
        messages = list(self._pending.values())
        self._pending.clear()
        return messages

    def _put(self, slot: int, message: M) -> None:
        self._pending[slot] = message
        self._ready.set()


async def send_until_closed(
    connection: Connection, *sources: Observable[WebSocketMessage]
) -> None:
    """Send the newest message of each source to `connection` until it closes.

    Messages published before the call or after the close are dropped.
    """
    with Outbox(*sources) as outbox:
        # Sources may go quiet, so the close is awaited on its own.
        async with asyncio.TaskGroup() as tasks:
            sender = tasks.create_task(_send_all(connection, outbox))
            await connection.wait_closed()
            sender.cancel()


async def _send_all(connection: Connection, outbox: Outbox[WebSocketMessage]) -> None:
    with contextlib.suppress(websockets.exceptions.ConnectionClosed):
        while True:
            for message in await outbox.take():
                await connection.send(json.dumps(message))
