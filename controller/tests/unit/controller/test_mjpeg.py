import asyncio

import aiohttp
import pytest
import yarl
from multidict import CIMultiDict, CIMultiDictProxy

from controller.mjpeg import (
    CameraStreamPart,
    format_part,
    is_retryable,
    read_part,
    read_stream,
)

_JPEG = b"\xff\xd8\xff\xd9"
_TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"


def _part(jpeg: bytes = _JPEG) -> bytes:
    return (
        b"\r\n--frame\r\nContent-Type: image/jpeg\r\n"
        + f"Content-Length: {len(jpeg)}\r\ntraceparent: {_TRACEPARENT}\r\n\r\n".encode()
        + jpeg
    )


def _stream(
    data: bytes, *, ended: bool = True, line_limit: int = 2**16
) -> asyncio.StreamReader:
    stream = asyncio.StreamReader(limit=line_limit)
    stream.feed_data(data)
    if ended:
        stream.feed_eof()
    return stream


@pytest.mark.asyncio
async def test_reads_the_jpeg_of_a_part() -> None:
    assert (await read_part(_stream(_part()))).jpeg == _JPEG


@pytest.mark.asyncio
async def test_reads_the_headers_of_a_part_by_lowercase_name() -> None:
    assert (await read_part(_stream(_part()))).headers["traceparent"] == _TRACEPARENT


@pytest.mark.asyncio
async def test_reads_parts_in_order() -> None:
    stream = _stream(_part(b"first") + _part(b"second"))
    await read_part(stream)

    assert (await read_part(stream)).jpeg == b"second"


@pytest.mark.asyncio
async def test_reads_a_part_before_the_next_boundary_arrives() -> None:
    stream = _stream(_part(), ended=False)

    assert (await asyncio.wait_for(read_part(stream), timeout=1)).jpeg == _JPEG


@pytest.mark.asyncio
async def test_reads_the_jpeg_by_its_content_length_not_by_the_boundary() -> None:
    jpeg = b"\xff\xd8\r\n--frame\r\n\xff\xd9"

    assert (await read_part(_stream(_part(jpeg)))).jpeg == jpeg


@pytest.mark.parametrize(
    "stream",
    [
        pytest.param(b"", id="empty"),
        pytest.param(_part()[:20], id="in-headers"),
        pytest.param(_part()[:-1], id="in-jpeg"),
    ],
)
@pytest.mark.asyncio
async def test_a_stream_that_ends_mid_part_raises_eof(stream: bytes) -> None:
    with pytest.raises(EOFError):
        await read_part(_stream(stream))


@pytest.mark.parametrize(
    "head",
    [
        pytest.param(b"Content-Length: four\r\n", id="non-numeric-length"),
        pytest.param(b"Content-Length 4\r\n", id="malformed-header-line"),
        pytest.param(b"X-Padding: " + bytes(100) + b"\r\n", id="over-long-line"),
    ],
)
@pytest.mark.asyncio
async def test_a_malformed_part_raises_a_payload_error(head: bytes) -> None:
    stream = _stream(b"\r\n--frame\r\n" + head + b"\r\n" + _JPEG, line_limit=64)

    with pytest.raises(aiohttp.ClientPayloadError):
        await read_part(stream)


def test_formats_a_part_with_its_boundary_and_headers() -> None:
    part = CameraStreamPart({"traceparent": _TRACEPARENT}, _JPEG)

    assert format_part(part) == _part()


def _status(status: int) -> aiohttp.ClientResponseError:
    url = yarl.URL("http://car.invalid/stream")
    request = aiohttp.RequestInfo(url, "GET", CIMultiDictProxy(CIMultiDict()), url)
    return aiohttp.ClientResponseError(request, (), status=status)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(_status(503), id="busy"),
        pytest.param(_status(404), id="not-found"),
        pytest.param(aiohttp.ServerDisconnectedError(), id="disconnected"),
        pytest.param(aiohttp.ServerTimeoutError(), id="stalled"),
        pytest.param(aiohttp.ClientPayloadError("lost"), id="lost-mid-body"),
        pytest.param(ConnectionRefusedError(), id="refused"),
        pytest.param(TimeoutError(), id="timed-out"),
        pytest.param(EOFError(), id="ended"),
    ],
)
def test_retries_after_an_error_that_can_pass(error: Exception) -> None:
    assert is_retryable(error) is True


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(aiohttp.InvalidUrlClientError("car.invalid"), id="invalid"),
        pytest.param(aiohttp.NonHttpUrlClientError("ws://car.invalid"), id="non-http"),
    ],
)
def test_gives_up_on_an_invalid_uri(error: Exception) -> None:
    assert is_retryable(error) is False


@pytest.mark.asyncio
async def test_stops_reconnecting_to_an_invalid_uri() -> None:
    def publish_dummy(_: CameraStreamPart) -> None:
        pass

    with pytest.raises(aiohttp.InvalidURL):
        await read_stream("car.invalid", publish_dummy)
