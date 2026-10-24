"""MjpegClient integration tests against a real HTTP Camera endpoint."""

import time

from controller.mjpeg import MjpegClient

from .test_doubles import car_camera_stub
from .waiting import wait_for

# Well inside MjpegClient's read timeout.
_PROMPT_EXIT_S = 1.0


def test_leaving_a_stalled_stream_does_not_wait_for_the_read_timeout() -> None:
    with car_camera_stub(stalled=True) as camera:
        client = MjpegClient(camera.uri)
        with client:
            assert wait_for(lambda: camera.open_connections == 1)
            start = time.monotonic()
        exit_s = time.monotonic() - start

    assert exit_s < _PROMPT_EXIT_S
