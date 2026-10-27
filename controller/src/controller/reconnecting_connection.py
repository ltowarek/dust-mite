"""Staying connected to a WebSocket peer: the reconnect policy and its loops."""

import asyncio
import dataclasses
import itertools
import logging
from collections.abc import Awaitable, Callable, Generator

import websockets.asyncio.client
import websockets.client
import websockets.exceptions
from websockets.asyncio.client import ClientConnection
from websockets.frames import CloseCode

from .outbox import send_until_closed
from .subject import Observable
from .websocket_message import WebSocketMessage

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

RETRY_DELAY_S = 1.0


@dataclasses.dataclass(frozen=True)
class DeliberateClose:
    """The peer closed the connection on purpose, giving `reason`."""

    reason: str


def classify_close(code: int | None, reason: str | None) -> DeliberateClose | None:
    """Return the deliberate close a closed connection's code and reason are.

    None means the peer went away and is to be retried.
    """
    if code in {None, CloseCode.ABNORMAL_CLOSURE, CloseCode.GOING_AWAY}:
        return None
    return DeliberateClose(reason or "")


def fatal_connect_error(error: Exception) -> Exception | None:
    """Return the error that ends reconnecting, or None to retry after `error`."""
    if isinstance(error, websockets.exceptions.InvalidHandshake):
        return None
    return websockets.client.process_exception(error)


def retry_delays() -> Generator[float]:
    """Yield the delay before each retry, in seconds."""
    yield from itertools.repeat(RETRY_DELAY_S)


async def stay_connected(
    uri: str, serve: Callable[[ClientConnection], Awaitable[None]]
) -> None:
    """Keep connecting to `uri` until cancelled, awaiting `serve` on each connection."""
    async for connection in websockets.asyncio.client.connect(
        uri,
        proxy=None,
        process_exception=fatal_connect_error,
        reconnect_delays=retry_delays,
    ):
        try:
            await serve(connection)
        finally:
            # Cancelling the loop body leaves the connection open until collected.
            await connection.close()
        # The loop resets its delays after any opened connection.
        await asyncio.sleep(RETRY_DELAY_S)


async def forward(uri: str, messages: Observable[WebSocketMessage]) -> None:
    """Send each message published on `messages` to `uri` until cancelled.

    Messages published while disconnected are dropped, and only the newest
    unsent one is kept, so a stalled peer never receives a backlog.
    """

    async def send_until_lost(connection: ClientConnection) -> None:
        logger.info("Connected to %s", uri)
        await send_until_closed(connection, messages)
        deliberate = classify_close(connection.close_code, connection.close_reason)
        if deliberate is None:
            logger.warning("Lost the connection to %s", uri)
        else:
            logger.warning("%s closed the connection: %s", uri, deliberate.reason)

    await stay_connected(uri, send_until_lost)
