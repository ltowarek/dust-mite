"""MJPEG over HTTP: a multipart/x-mixed-replace stream of JPEG parts."""

import asyncio
import dataclasses
import http.client
import io
import logging
from collections.abc import Callable
from typing import Protocol

import aiohttp
import aiohttp.http_exceptions

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

BOUNDARY = "frame"
CONTENT_TYPE = f"multipart/x-mixed-replace;boundary={BOUNDARY}"

# A stream that sends nothing for this long is treated as dropped.
_READ_TIMEOUT_S = 5.0


class _Readable(Protocol):
    async def readline(self) -> bytes: ...

    async def readexactly(self, n: int) -> bytes: ...


@dataclasses.dataclass(frozen=True)
class CameraStreamPart:
    """One JPEG of an MJPEG stream and its part headers, keyed by lowercase name."""

    headers: dict[str, str]
    jpeg: bytes


async def read_part(stream: _Readable) -> CameraStreamPart:
    """Read the next part of `stream`, raising `EOFError` if the stream ends first.

    A part that cannot be framed raises `aiohttp.ClientPayloadError`.
    """
    try:
        line = await stream.readline()
        while not line.startswith(b"--"):
            if not line:
                raise EOFError
            line = await stream.readline()
        head: list[bytes] = []
        while (line := await stream.readline()) not in {b"\r\n", b"\n"}:
            if not line:
                raise EOFError
            head.append(line)
        message = http.client.parse_headers(io.BytesIO(b"".join(head)))
        headers = {name.lower(): value for name, value in message.items()}
        length = int(headers["content-length"])
        return CameraStreamPart(headers, await stream.readexactly(length))
    except (
        KeyError,
        ValueError,
        http.client.HTTPException,
        aiohttp.http_exceptions.BadHttpMessage,
    ) as error:
        raise aiohttp.ClientPayloadError(repr(error)) from error


def format_part(part: CameraStreamPart) -> bytes:
    """Return `part` as it goes on the wire, its boundary first."""
    headers = {
        "Content-Type": "image/jpeg",
        "Content-Length": str(len(part.jpeg)),
        **part.headers,
    }
    head = "".join(f"{name}: {value}\r\n" for name, value in headers.items())
    return f"\r\n--{BOUNDARY}\r\n{head}\r\n".encode("latin-1") + part.jpeg


def is_retryable(error: Exception) -> bool:
    """Return whether a new connection could succeed after `error`."""
    if isinstance(error, aiohttp.InvalidURL | aiohttp.NonHttpUrlClientError):
        return False
    return isinstance(error, aiohttp.ClientError | OSError | EOFError)


async def read_stream(uri: str, publish: Callable[[CameraStreamPart], None]) -> None:
    """Publish each part of the stream at `uri`, reconnecting after each loss."""
    retry_delay_s = 1.0
    timeout = aiohttp.ClientTimeout(total=None, sock_read=_READ_TIMEOUT_S)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                async with session.get(uri, raise_for_status=True) as response:
                    logger.info("Stream connected: %s", uri)
                    while True:
                        publish(await read_part(response.content))
            except Exception as error:
                if not is_retryable(error):
                    raise
                logger.warning("Lost the stream from %s: %r", uri, error)
            await asyncio.sleep(retry_delay_s)
