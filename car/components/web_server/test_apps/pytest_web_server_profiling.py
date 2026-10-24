"""Profile exports must leave the web server enough internal RAM while clients stream.

Needs the test app built with sdkconfig.defaults.profiling into build_profiling/.
"""

import contextlib
import threading

import pytest
from helpers import CLOSE_TIMEOUT_S, OPEN_TIMEOUT_S, CarEndpoints, Endpoint, drain, open_stream, read_part
from pytest_embedded import Dut
from websockets.sync.client import connect

EXPORT_WINDOWS = 6
EXPORT_LINE = rb'profiles export: \d+ bytes, internal RAM drop (\d+) bytes'
# sdkconfig.defaults.profiling exports every second; the first export waits for a full window.
EXPORT_TIMEOUT_S = 30.0
# Streaming alone moves internal RAM by up to about 20 KB between two exports.
INTERNAL_RAM_DROP_BUDGET_BYTES = 48 * 1024


def _drain_stream(camera: Endpoint, stop: threading.Event) -> None:
    with open_stream(camera) as stream, contextlib.suppress(ConnectionError, OSError):
        while not stop.is_set():
            read_part(stream)


@pytest.fixture(autouse=True)
def _profiling_build(dut: Dut) -> None:
    if dut.app.sdkconfig.get('ESP_OPENTELEMETRY_PROFILING_ENABLED') is not True:
        pytest.skip('needs a profiling build (sdkconfig.defaults.profiling)')


@pytest.mark.dut(reason='measures internal RAM with Wi-Fi and the camera running')
def test_profile_exports_leave_internal_ram_to_the_server(dut: Dut, car: CarEndpoints) -> None:
    stop = threading.Event()
    telemetry = connect(car.telemetry.uri, open_timeout=OPEN_TIMEOUT_S, close_timeout=CLOSE_TIMEOUT_S)
    readers = [
        threading.Thread(target=_drain_stream, args=(car.camera, stop), daemon=True),
        threading.Thread(target=drain, args=(telemetry, stop), daemon=True),
    ]
    for reader in readers:
        reader.start()

    drops = []
    try:
        # The first export after streaming starts covers a window from before it.
        dut.expect_exact('Stream started', timeout=OPEN_TIMEOUT_S)
        dut.expect(EXPORT_LINE, timeout=EXPORT_TIMEOUT_S)
        for _ in range(EXPORT_WINDOWS):
            match = dut.expect(EXPORT_LINE, timeout=EXPORT_TIMEOUT_S)
            drops.append(int(match.group(1)))
    finally:
        stop.set()
        telemetry.close()
        for reader in readers:
            reader.join()

    assert max(drops) <= INTERNAL_RAM_DROP_BUDGET_BYTES, f'internal RAM drop per profile export: {drops}'
