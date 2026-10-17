"""Every sdkconfig overlay must keep the car running while it streams.

CI only builds the debug overlays, and what breaks in one at runtime, such as a crash loop under load,
does not show in a build. scripts/run_tests.sh builds the base firmware into build/ and each
car/sdkconfig.defaults.<overlay> into build_<overlay>/; each case flashes one, streams the Camera
endpoint and fails on any reset or fault the firmware prints.
"""

import threading
from pathlib import Path

import pexpect
import pytest
from pytest_embedded import Dut
from websockets.sync.client import connect

from helpers import CLOSE_TIMEOUT_S, OPEN_TIMEOUT_S, car_endpoints, drain, get_dut_ip

CAR_ROOT = Path(__file__).resolve().parents[2]
READY = b'Serving every endpoint'
BOOT_TIMEOUT_S = 70.0
# Several profile exports (CONFIG_ESP_OPENTELEMETRY_PROFILING_EXPORT_INTERVAL_MS) reach the
# exporters, the watchdog and the camera under load.
STREAM_S = 60.0
FAULT = rb'rst:0x|Rebooting\.\.\.|Guru Meditation|assert failed|abort\(\) was called|stack overflow'
# A profiling build that warns has stopped exporting profiles: no exporter installed, or an export
# that did not reach the symbolizer.
PROFILING_WARNING = rb'W \(\d+\) esp_otel_profil'

_OVERLAYS = [pytest.param('build', id='base')] + [
    pytest.param(f'build_{defaults.suffix[1:]}', id=defaults.suffix[1:])
    for defaults in sorted(CAR_ROOT.glob('sdkconfig.defaults.*'))
]


def _fault_pattern(dut: Dut) -> bytes:
    if dut.app.sdkconfig.get('ESP_OPENTELEMETRY_PROFILING_ENABLED') is True:
        return FAULT + b'|' + PROFILING_WARNING
    return FAULT


def _first_fault(dut: Dut, fault: bytes) -> str | None:
    car = car_endpoints(get_dut_ip(dut))
    booted = dut.expect([READY, fault], timeout=BOOT_TIMEOUT_S).group(0)
    if booted != READY:
        return booted.decode()
    stop = threading.Event()
    with connect(car.camera.uri, open_timeout=OPEN_TIMEOUT_S, close_timeout=CLOSE_TIMEOUT_S) as stream:
        reader = threading.Thread(target=drain, args=(stream, stop), daemon=True)
        reader.start()
        try:
            dut.expect_exact('Stream started', timeout=OPEN_TIMEOUT_S)
            try:
                return dut.expect(fault, timeout=STREAM_S).group(0).decode()
            except pexpect.TIMEOUT:
                return None
        finally:
            stop.set()


@pytest.mark.parametrize('build_dir', _OVERLAYS, indirect=True)
def test_overlay_survives_streaming(dut: Dut) -> None:
    fault = _first_fault(dut, _fault_pattern(dut))

    assert fault is None, f'the car printed {fault!r}'
