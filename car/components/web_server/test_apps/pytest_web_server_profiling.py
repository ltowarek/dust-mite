"""On the car, the profiler must leave the server it samples the internal RAM it runs on.

Needs the test app built with sdkconfig.defaults.profiling and flashed to the car. Every profile
export prints how far internal RAM fell since the previous export, a window that holds the
sampler's aggregation and the export's document build while clients stream from the server.
esp-opentelemetry-cpp's test/profiles_export_memory reproduces the crash this guards against in
QEMU; this test measures what is left on real hardware, with Wi-Fi and the camera running.
"""

import threading

import pytest
from helpers import CarEndpoints
from pytest_embedded import Dut
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

OPEN_TIMEOUT_S = 8.0
CLOSE_TIMEOUT_S = 10.0
EXPORT_WINDOWS = 6
EXPORT_LINE = rb'profiles export: \d+ bytes, internal RAM drop (\d+) bytes'
# sdkconfig.defaults.profiling exports every second; the first export waits for a full window.
EXPORT_TIMEOUT_S = 30.0
# Streaming alone moves the car's internal RAM by up to about 20 KB between two exports. An
# exporter that builds its document there takes 110-160 KB, nearly all the car has free.
INTERNAL_RAM_DROP_BUDGET_BYTES = 48 * 1024


@pytest.fixture(autouse=True)
def _profiling_build(dut: Dut) -> None:
    if dut.app.sdkconfig.get('ESP_OPENTELEMETRY_PROFILING_ENABLED') is not True:
        pytest.skip('needs a profiling build (sdkconfig.defaults.profiling)')


def _drain(ws, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            ws.recv(timeout=1)
        except TimeoutError:
            continue
        except ConnectionClosed:
            return


@pytest.mark.dut(reason='measures internal RAM with Wi-Fi and the camera running')
def test_profile_exports_leave_internal_ram_to_the_server(dut: Dut, car: CarEndpoints) -> None:
    stop = threading.Event()
    clients = [
        connect(endpoint.uri, open_timeout=OPEN_TIMEOUT_S, close_timeout=CLOSE_TIMEOUT_S)
        for endpoint in (car.camera, car.telemetry)
    ]
    readers = [threading.Thread(target=_drain, args=(ws, stop), daemon=True) for ws in clients]
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
