import http.client
import time
import urllib.parse

import pytest

from controller.mjpeg import read_part
from controller.streamer import StreamerSettings

_FRAMES = 100
# The camera itself reaches 25 FPS; the network costs a few.
_MIN_FPS = 22


@pytest.fixture
def stream_client_uri(streamer_settings: StreamerSettings) -> str:
    return streamer_settings.camera_uri


@pytest.mark.dut
def test_performance(stream_client_uri: str) -> None:
    uri = urllib.parse.urlsplit(stream_client_uri)
    connection = http.client.HTTPConnection(uri.hostname or "", uri.port, timeout=5)
    try:
        connection.request("GET", uri.path)
        stream = connection.getresponse()
        read_part(stream)
        start = time.monotonic()
        for _ in range(_FRAMES):
            read_part(stream)
        fps = _FRAMES / (time.monotonic() - start)
    finally:
        connection.close()

    assert fps >= _MIN_FPS
