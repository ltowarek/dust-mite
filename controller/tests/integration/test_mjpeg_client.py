"""MjpegClient integration tests against a real HTTP Camera endpoint."""

import time

from controller.mjpeg import MjpegClient

from .test_doubles import car_camera_stub
from .waiting import wait_for

# MjpegClient's read timeout, plus a margin for its worker to notice.
_STALLED_EXIT_S = 6.0


def test_leaving_a_stalled_stream_takes_at_most_the_read_timeout() -> None:
    with car_camera_stub(stalled=True) as camera:
        client = MjpegClient(camera.uri)
        with client:
            assert wait_for(lambda: camera.open_connections == 1)
            start = time.monotonic()
        exit_s = time.monotonic() - start

    assert exit_s < _STALLED_EXIT_S
