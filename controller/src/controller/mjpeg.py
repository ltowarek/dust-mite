"""MJPEG over HTTP: a multipart/x-mixed-replace stream of JPEG parts."""

import contextlib
import dataclasses
import http
import http.client
import logging
import queue
import threading
from types import TracebackType
from typing import Protocol, Self

import requests
import urllib3.exceptions

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# A stream that sends nothing for this long is treated as dropped.
_READ_TIMEOUT_S = 5.0
_RECONNECT_DELAY_S = 1.0


class _Readable(Protocol):
    def readline(self, size: int = -1, /) -> bytes: ...

    def read(self, size: int = -1, /) -> bytes: ...


@dataclasses.dataclass(frozen=True)
class Part:
    """One JPEG of an MJPEG stream and its part headers, keyed by lowercase name."""

    headers: dict[str, str]
    jpeg: bytes


def read_part(stream: _Readable) -> Part:
    """Read the next part of `stream`, raising `EOFError` if the stream ends first."""
    line = stream.readline()
    while not line.startswith(b"--"):
        if not line:
            raise EOFError
        line = stream.readline()
    message = http.client.parse_headers(stream)
    headers = {name.lower(): value for name, value in message.items()}
    if "content-length" not in headers:
        raise EOFError
    length = int(headers["content-length"])
    jpeg = stream.read(length)
    if len(jpeg) < length:
        raise EOFError
    return Part(headers, jpeg)


class StreamRefusedError(Exception):
    """The server answered the stream request with something other than 200 OK."""


class MjpegClient:
    """Reads an MJPEG stream, reconnecting until closed, keeping only the newest part.

    Use as a context manager: it connects on entry and disconnects on exit.
    """

    def __init__(self, uri: str) -> None:
        """Initialize the object."""
        self._uri = uri
        self._stop_event = threading.Event()
        self._parts: queue.Queue[Part] = queue.Queue(1)
        self._worker = threading.Thread(target=self._worker_main)

    def __enter__(self) -> Self:
        """Start reading the stream."""
        self._worker.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: TracebackType | None,
    ) -> None:
        """Stop reading and disconnect; a stalled stream takes its read timeout."""
        self._stop_event.set()
        self._worker.join()

    def recv(self, timeout: float) -> Part:
        """Return the newest part; raise `TimeoutError` if none arrives in `timeout`."""
        try:
            return self._parts.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError from None

    def _worker_main(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._read_stream()
            except (
                OSError,
                EOFError,
                requests.RequestException,
                urllib3.exceptions.HTTPError,
                StreamRefusedError,
            ) as e:
                if not self._stop_event.is_set():
                    logger.warning("Lost the stream from %s: %r", self._uri, e)
                self._stop_event.wait(_RECONNECT_DELAY_S)

    def _read_stream(self) -> None:
        with requests.get(self._uri, stream=True, timeout=_READ_TIMEOUT_S) as response:
            if response.status_code != http.HTTPStatus.OK:
                raise StreamRefusedError(response.status_code)
            logger.info("Stream connected: %s", self._uri)
            while not self._stop_event.is_set():
                self._keep_newest(read_part(response.raw))

    def _keep_newest(self, part: Part) -> None:
        with contextlib.suppress(queue.Empty):
            self._parts.get_nowait()
        self._parts.put_nowait(part)
