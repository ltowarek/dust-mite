"""Every sdkconfig overlay must keep the car running while it streams.

CI only builds the debug overlays, and what breaks in one at runtime, such as a crash loop under load,
does not show in a build. scripts/run_tests.sh builds each overlay into the directory
named below; each case flashes one, streams the Camera endpoint and fails on any reset or fault the
firmware prints.
"""

import threading

import pexpect
import pytest
from pytest_embedded import Dut
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from helpers import car_endpoints, get_dut_ip

OPEN_TIMEOUT_S = 8.0
CLOSE_TIMEOUT_S = 10.0
# Profiling exports every 5 s; a few windows' worth of streaming reaches the exporters, the
# watchdog and the camera under load.
STREAM_S = 60.0
FAULT = rb'rst:0x|Rebooting\.\.\.|Guru Meditation|assert failed|abort\(\) was called|stack overflow'

_OVERLAYS = [
    pytest.param('build', id='base'),
    pytest.param('build_profiling', id='profiling'),
    pytest.param('build_all', id='all'),
]


def _drain(ws, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            ws.recv(timeout=1)
        except TimeoutError:
            continue
        except ConnectionClosed:
            return


@pytest.mark.parametrize('build_dir', _OVERLAYS, indirect=True)
def test_overlay_survives_streaming(dut: Dut) -> None:
    car = car_endpoints(get_dut_ip(dut))
    dut.expect(r'Serving every endpoint', timeout=70)

    stop = threading.Event()
    with connect(car.camera.uri, open_timeout=OPEN_TIMEOUT_S, close_timeout=CLOSE_TIMEOUT_S) as stream:
        reader = threading.Thread(target=_drain, args=(stream, stop), daemon=True)
        reader.start()
        try:
            dut.expect_exact('Stream started', timeout=OPEN_TIMEOUT_S)
            try:
                fault = dut.expect(FAULT, timeout=STREAM_S).group(0).decode()
            except pexpect.TIMEOUT:
                fault = None
        finally:
            stop.set()

    assert fault is None, f'the car printed {fault!r} while streaming'
