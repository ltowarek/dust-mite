"""Every build, base and each sdkconfig overlay, must keep the car streaming Camera frames.

Flashes build/ and each build_<overlay>/ that scripts/run_tests.sh builds.
"""

import time
from pathlib import Path

import pytest
from pytest_embedded import Dut

from helpers import Endpoint, car_endpoints, get_dut_ip, open_stream, read_part

CAR_ROOT = Path(__file__).resolve().parents[2]
READY = 'Serving every endpoint'
BOOT_TIMEOUT_S = 70.0
# Long enough for several profile exports in the profiling build.
STREAM_S = 60.0
# The camera sends several frames a second; a reset drops the connection and ends them.
MAX_FRAME_GAP_S = 5.0

_BUILDS = [pytest.param('build', id='base')] + [
    pytest.param(f'build_{defaults.suffix[1:]}', id=defaults.suffix[1:])
    for defaults in sorted(CAR_ROOT.glob('sdkconfig.defaults.*'))
]


def _longest_frame_gap(camera: Endpoint) -> float:
    start = time.monotonic()
    end = start + STREAM_S
    edges = [start]
    with open_stream(camera) as stream:
        while time.monotonic() < end:
            try:
                read_part(stream)
            except (ConnectionError, OSError):
                break
            edges.append(time.monotonic())
    edges.append(end)
    return max(later - earlier for earlier, later in zip(edges, edges[1:]))


@pytest.mark.parametrize('build_dir', _BUILDS, indirect=True)
def test_streams_without_gaps(dut: Dut) -> None:
    car = car_endpoints(get_dut_ip(dut))
    dut.expect_exact(READY, timeout=BOOT_TIMEOUT_S)

    gap = _longest_frame_gap(car.camera)

    assert gap <= MAX_FRAME_GAP_S, f'no Camera frame for {gap:.1f} s'
