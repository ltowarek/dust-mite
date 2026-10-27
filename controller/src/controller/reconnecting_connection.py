"""A write-only WebSocket connection that stays connected, and its reconnect policy."""

import asyncio
import contextlib
import dataclasses
import itertools
import logging
from collections.abc import Awaitable, Callable, Generator

import websockets.asyncio.client
import websockets.exceptions
from websockets.asyncio.client import ClientConnection
from websockets.frames import Close, CloseCode

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

RETRY_DELAY_S = 1.0


@dataclasses.dataclass(frozen=True)
class DeliberateClose:
    """The peer closed the connection on purpose, giving `reason`."""

    reason: str


def classify_close(close: Close | None) -> DeliberateClose | None:
    """Return the deliberate close `close` is, or None if the peer is to be retried.

    `close` is the close frame the peer sent, None if it sent none.
    """
    if close is None or close.code == CloseCode.GOING_AWAY:
        return None
    return DeliberateClose(close.reason)


def retry_delays() -> Generator[float]:
    """Yield the delay before each retry, in seconds."""
    yield from itertools.repeat(RETRY_DELAY_S)


async def stay_connected(
    uri: str, serve: Callable[[ClientConnection], Awaitable[None]]
) -> None:
    """Keep connecting to `uri` until cancelled, awaiting `serve` on each connection."""
    async for connection in websockets.asyncio.client.connect(
        uri, proxy=None, reconnect_delays=retry_delays
    ):
        try:
            await serve(connection)
        finally:
            # Cancelling the loop body leaves the connection open until collected.
            await connection.close()
        # The loop resets its delays after any opened connection.
        await asyncio.sleep(RETRY_DELAY_S)


class ReconnectingConnection:
    """A write-only WebSocket connection to `uri`, reconnecting while `run` runs.

    Messages sent while disconnected are dropped.
    """

    def __init__(self, uri: str) -> None:
        """Initialize the object."""
        self._uri = uri
        self._outgoing: asyncio.Queue[str] | None = None

    def send(self, message: str) -> None:
        """Send `message` if connected, otherwise drop it."""
        if self._outgoing is not None:
            self._outgoing.put_nowait(message)

    async def run(self) -> None:
        """Stay connected until cancelled."""
        await stay_connected(self._uri, self._serve)

    async def _serve(self, connection: ClientConnection) -> None:
        logger.info("Connected to %s", self._uri)
        outgoing: asyncio.Queue[str] = asyncio.Queue()
        self._outgoing = outgoing
        try:
            async with asyncio.TaskGroup() as tasks:
                sender = tasks.create_task(_send_all(connection, outgoing))
                close = await _closed(connection)
                sender.cancel()
        finally:
            self._outgoing = None
        deliberate = classify_close(close)
        if deliberate is None:
            logger.warning("Lost the connection to %s", self._uri)
        else:
            logger.warning("%s closed the connection: %s", self._uri, deliberate.reason)


async def _send_all(connection: ClientConnection, outgoing: asyncio.Queue[str]) -> None:
    with contextlib.suppress(websockets.exceptions.ConnectionClosed):
        while True:
            await connection.send(await outgoing.get())


async def _closed(connection: ClientConnection) -> Close | None:
    """Return the peer's close frame once `connection` closes, discarding messages."""
    try:
        while True:
            await connection.recv()
    except websockets.exceptions.ConnectionClosed as e:
        return e.rcvd
