"""MJPEG over HTTP: a multipart/x-mixed-replace stream of JPEG parts."""

import asyncio
import dataclasses
import http.client
import io
import logging
from collections.abc import Callable

import aiohttp

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

BOUNDARY = "frame"
CONTENT_TYPE = f"multipart/x-mixed-replace;boundary={BOUNDARY}"


@dataclasses.dataclass(frozen=True)
class CameraStreamPart:
    """One JPEG of an MJPEG stream and its part headers, keyed by lowercase name."""

    headers: dict[str, str]
    jpeg: bytes


async def read_part(stream: aiohttp.StreamReader) -> CameraStreamPart:
    """Read the next part of `stream`, raising `EOFError` if the stream ends first."""
    await _read_through(stream, f"--{BOUNDARY}\r\n".encode())
    head = await _read_through(stream, b"\r\n\r\n")
    message = http.client.parse_headers(io.BytesIO(head))
    headers = {name.lower(): value for name, value in message.items()}
    length = int(headers["content-length"])
    return CameraStreamPart(headers, await stream.readexactly(length))


async def _read_through(stream: aiohttp.StreamReader, separator: bytes) -> bytes:
    # At the end of the stream, readuntil returns what it has instead of raising.
    data = await stream.readuntil(separator)
    if not data.endswith(separator):
        raise EOFError
    return data


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
    """Return whether retrying could succeed after opening failed with `error`."""
    if isinstance(error, aiohttp.InvalidURL | aiohttp.NonHttpUrlClientError):
        return False
    return isinstance(error, aiohttp.ClientError | OSError)


async def read_stream(uri: str, publish: Callable[[CameraStreamPart], None]) -> None:
    """Publish each part of the stream at `uri`, reconnecting after each loss."""
    retry_delay_s = 1.0
    timeout = aiohttp.ClientTimeout(total=None, sock_read=5.0)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                async with session.get(uri, raise_for_status=True) as response:
                    logger.info("Stream connected: %s", uri)
                    try:
                        while True:
                            publish(await read_part(response.content))
                    # Corrupt data must never stop the streamer.
                    except Exception:
                        logger.exception("Lost the stream from %s", uri)
            except Exception as error:
                if not is_retryable(error):
                    raise
                logger.warning("Could not connect to %s: %r", uri, error)
            await asyncio.sleep(retry_delay_s)
