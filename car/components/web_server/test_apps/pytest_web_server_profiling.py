"""Profile exports must leave the web server enough internal RAM while clients stream.

Needs the test app built with sdkconfig.defaults.profiling into build_profiling/.
"""

import threading

import pytest
from helpers import CLOSE_TIMEOUT_S, OPEN_TIMEOUT_S, CarEndpoints, drain
from pytest_embedded import Dut
from websockets.sync.client import connect

EXPORT_WINDOWS = 6
EXPORT_LINE = rb'profiles export: \d+ bytes, internal RAM drop (\d+) bytes'
# sdkconfig.defaults.profiling exports every second; the first export waits for a full window.
EXPORT_TIMEOUT_S = 30.0
# Streaming alone moves the car's internal RAM by up to about 20 KB between two exports, and a
# document built in internal RAM grows with the profile to most of what the car has free.
INTERNAL_RAM_DROP_BUDGET_BYTES = 48 * 1024


@pytest.fixture(autouse=True)
def _profiling_build(dut: Dut) -> None:
    if dut.app.sdkconfig.get('ESP_OPENTELEMETRY_PROFILING_ENABLED') is not True:
        pytest.skip('needs a profiling build (sdkconfig.defaults.profiling)')


@pytest.mark.dut(reason='measures internal RAM with Wi-Fi and the camera running')
def test_profile_exports_leave_internal_ram_to_the_server(dut: Dut, car: CarEndpoints) -> None:
    stop = threading.Event()
    clients = [
        connect(endpoint.uri, open_timeout=OPEN_TIMEOUT_S, close_timeout=CLOSE_TIMEOUT_S)
        for endpoint in (car.camera, car.telemetry)
    ]
    readers = [threading.Thread(target=drain, args=(ws, stop), daemon=True) for ws in clients]
    for reader in readers:
        reader.start()

    drops = []
    try:
        # Exports printed before the clients connected are still buffered; the server logs this
        # only once the camera client is in, and the export after it covers a window that started
        # before streaming (and the server's session setup), so it is not measured either.
        dut.expect_exact('Stream started', timeout=OPEN_TIMEOUT_S)
        dut.expect(EXPORT_LINE, timeout=EXPORT_TIMEOUT_S)
        for _ in range(EXPORT_WINDOWS):
            match = dut.expect(EXPORT_LINE, timeout=EXPORT_TIMEOUT_S)
            drops.append(int(match.group(1)))
    finally:
        stop.set()
        for ws in clients:
            ws.close()

    assert max(drops) <= INTERNAL_RAM_DROP_BUDGET_BYTES, f'internal RAM drop per profile export: {drops}'
