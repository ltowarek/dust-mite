import io

import pytest

from controller.mjpeg import CameraStreamPart, format_part, read_part

_JPEG = b"\xff\xd8\xff\xd9"
_TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"


def _part(jpeg: bytes = _JPEG) -> bytes:
    return (
        b"\r\n--frame\r\nContent-Type: image/jpeg\r\n"
        + f"Content-Length: {len(jpeg)}\r\ntraceparent: {_TRACEPARENT}\r\n\r\n".encode()
        + jpeg
    )


def test_reads_the_jpeg_of_a_part() -> None:
    assert read_part(io.BytesIO(_part())).jpeg == _JPEG


def test_reads_the_headers_of_a_part_by_lowercase_name() -> None:
    assert read_part(io.BytesIO(_part())).headers["traceparent"] == _TRACEPARENT


def test_reads_parts_in_order() -> None:
    stream = io.BytesIO(_part(b"first") + _part(b"second"))
    read_part(stream)

    assert read_part(stream).jpeg == b"second"


@pytest.mark.parametrize(
    "stream",
    [
        pytest.param(b"", id="empty"),
        pytest.param(_part()[:20], id="in-headers"),
        pytest.param(_part()[:-1], id="in-jpeg"),
    ],
)
def test_a_stream_that_ends_mid_part_raises_eof(stream: bytes) -> None:
    with pytest.raises(EOFError):
        read_part(io.BytesIO(stream))


def _round_trip() -> CameraStreamPart:
    return read_part(
        io.BytesIO(format_part(CameraStreamPart({"traceparent": _TRACEPARENT}, _JPEG)))
    )


def test_a_formatted_part_reads_back_its_jpeg() -> None:
    assert _round_trip().jpeg == _JPEG


def test_a_formatted_part_reads_back_its_headers() -> None:
    assert _round_trip().headers["traceparent"] == _TRACEPARENT
