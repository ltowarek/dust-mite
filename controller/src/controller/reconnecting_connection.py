"""Staying connected to a WebSocket peer: the reconnect policy and its loop."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import NoReturn

import websockets.asyncio.client
import websockets.exceptions
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.connection import Connection
from websockets.frames import CloseCode

from .outbox import Broadcast, send_json, send_until_closed
from .websocket_message import WebSocketMessage

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def deliberate_close_reason(code: int | None, reason: str | None) -> str | None:
    """Return the reason of a close the peer chose, or None if it went away."""
    if code in {None, CloseCode.ABNORMAL_CLOSURE, CloseCode.GOING_AWAY}:
        return None
    return reason or ""


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
) -> NoReturn:
    """Await `handler` on a connection to `uri`, again after each retryable loss."""
    retry_delay_s = 1.0
    while True:
        try:
            # Each send waits for the peer, so a stalled peer is sent no backlog.
            async with websockets.asyncio.client.connect(
                uri, proxy=None, write_limit=0
            ) as connection:
                await handler(connection)
        except Exception as error:
            if not is_retryable(error):
                raise
        await asyncio.sleep(retry_delay_s)


async def send_until_lost[M](
    uri: str,
    connection: ClientConnection,
    send: Callable[[Connection, M], Awaitable[None]],
    *sources: Broadcast[M],
) -> str | None:
    """Send to `connection` until it closes; return the reason of a deliberate close."""
    logger.info("Connected to %s", uri)
    await send_until_closed(connection, send, *sources)
    reason = deliberate_close_reason(connection.close_code, connection.close_reason)
    if reason is None:
        logger.warning("Lost the connection to %s", uri)
    return reason


async def forward(uri: str, messages: Broadcast[WebSocketMessage]) -> None:
    """Send each message published on `messages` to `uri` until cancelled."""

    async def send_until_closed_by_peer(connection: ClientConnection) -> None:
        reason = await send_until_lost(uri, connection, send_json, messages)
        if reason is not None:
            logger.warning("%s closed the connection: %s", uri, reason)

    await stay_connected(uri, send_until_closed_by_peer)
