"""Staying connected to a WebSocket peer: the reconnect policy and its loop."""

import asyncio
import dataclasses
import logging
from collections.abc import Awaitable, Callable

import websockets.asyncio.client
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


def is_retryable(error: Exception) -> bool:
    """Return whether a new connection could succeed after `error`."""
    return isinstance(
        error,
        OSError
        | TimeoutError
        | websockets.exceptions.InvalidHandshake
        | websockets.exceptions.ConnectionClosed,
    )


async def stay_connected(
    uri: str, handler: Callable[[ClientConnection], Awaitable[None]]
) -> None:
    """Await `handler` on a connection to `uri`, again 1 s after each loss."""
    while True:
        try:
            async with websockets.asyncio.client.connect(uri, proxy=None) as connection:
                await handler(connection)
        except Exception as error:
            if not is_retryable(error):
                raise
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
