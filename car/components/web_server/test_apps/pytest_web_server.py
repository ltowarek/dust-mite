import asyncio
import json
import math
import socket
import threading
import time
from collections.abc import Callable
from operator import attrgetter

import pexpect
import pytest
import websockets
from helpers import CLOSE_TIMEOUT_S, OPEN_TIMEOUT_S, CarEndpoints, Endpoint
from pytest_embedded import Dut
from websockets.sync.client import connect

# How long to wait for a drive command to show up in the car's log before calling it lost.
COMMAND_ARRIVAL_TIMEOUT_S = 15.0

BRAKE = 3

# A drive command's normal round trip to the car, with Wi-Fi jitter.
COMMAND_DELAY_BUDGET_S = 0.25

_ENDPOINTS = [pytest.param(attrgetter(name), id=name) for name in ('drive', 'camera', 'telemetry')]
_PUSH_ENDPOINTS = [pytest.param(attrgetter(name), id=name) for name in ('camera', 'telemetry')]

_SLOW_CLIENT_REASON = (
    "QEMU's user-mode network buffers what the client does not read, so the car's sends are never throttled"
)


def _close_in_background(ws) -> tuple[threading.Event, float]:
    """Close off-thread: websockets.sync can block past close_timeout, and a test must
    report that rather than hang on it."""
    done = threading.Event()

    def _close() -> None:
        try:
            ws.close()
        finally:
            done.set()

    started = time.monotonic()
    threading.Thread(target=_close, daemon=True).start()
    return done, started


def _connect_through_small_window(endpoint: Endpoint, rcvbuf_bytes: int):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf_bytes)
    sock.settimeout(OPEN_TIMEOUT_S)
    sock.connect((endpoint.host, endpoint.port))
    return connect(endpoint.uri, sock=sock, open_timeout=OPEN_TIMEOUT_S, close_timeout=CLOSE_TIMEOUT_S, max_queue=1)


def _expect_brake(dut: Dut, value: int, timeout: float) -> None:
    dut.expect(rf'JSON=\{{"command": {BRAKE}, "value": {value}\}}', timeout=timeout)


def test_unity_cases_pass(dut: Dut) -> None:
    dut.run_all_single_board_cases(reset=True, timeout=60)


@pytest.mark.parametrize('endpoint_of', _ENDPOINTS)
def test_web_server_endpoint_reachable(
    dut: Dut, car: CarEndpoints, endpoint_of: Callable[[CarEndpoints], Endpoint]
) -> None:
    async def run():
        async with websockets.connect(endpoint_of(car).uri):
            pass

    asyncio.run(run())


@pytest.mark.dut(reason=_SLOW_CLIENT_REASON)
def test_command_not_delayed_by_slow_stream_reader(dut: Dut, car: CarEndpoints) -> None:
    command_count = 150
    command_interval_s = 0.1
    slow_read_interval_s = 0.3
    slow_read_rcvbuf_bytes = 8192

    stream = _connect_through_small_window(car.camera, slow_read_rcvbuf_bytes)
    stop = threading.Event()

    def _read_slowly() -> None:
        while not stop.is_set():
            stream.recv(timeout=8)
            stop.wait(slow_read_interval_s)

    reader = threading.Thread(target=_read_slowly, daemon=True)
    reader.start()

    drive = connect(car.drive.uri, open_timeout=OPEN_TIMEOUT_S, close_timeout=CLOSE_TIMEOUT_S)
    sent_at: dict[int, float] = {}

    def _send_commands() -> None:
        for value in range(command_count):
            sent_at[value] = time.monotonic()
            drive.send(json.dumps({'command': BRAKE, 'value': value}))
            time.sleep(command_interval_s)

    sender = threading.Thread(target=_send_commands, daemon=True)
    sender.start()

    delays = []
    try:
        for value in range(command_count):
            _expect_brake(dut, value, timeout=COMMAND_ARRIVAL_TIMEOUT_S)
            delays.append(time.monotonic() - sent_at[value])
    finally:
        stop.set()
        sender.join(timeout=command_count * command_interval_s + 5)
        _close_in_background(drive)
        _close_in_background(stream)

    worst = max(delays)
    assert worst < COMMAND_DELAY_BUDGET_S, (
        f'drive command took {worst:.2f}s to reach the car while /stream was read slowly (delays: {delays})'
    )


def _command_delay(dut: Dut, drive, value: int) -> float:
    """How long a drive command takes to reach the car, or infinity if it never arrives."""
    sent_at = time.monotonic()
    drive.send(json.dumps({'command': BRAKE, 'value': value}))
    try:
        _expect_brake(dut, value, timeout=COMMAND_ARRIVAL_TIMEOUT_S)
    except pexpect.TIMEOUT:
        return math.inf
    return time.monotonic() - sent_at


@pytest.mark.dut(reason=_SLOW_CLIENT_REASON)
@pytest.mark.parametrize('endpoint_of', _PUSH_ENDPOINTS)
def test_command_still_read_after_close_while_push_send_stalls(
    dut: Dut, car: CarEndpoints, endpoint_of: Callable[[CarEndpoints], Endpoint]
) -> None:
    stalled_rcvbuf_bytes = 1024
    stall_settle_s = 60.0
    stalled_command_value = 7

    stalled = _connect_through_small_window(endpoint_of(car), stalled_rcvbuf_bytes)
    time.sleep(stall_settle_s)

    try:
        with connect(car.drive.uri, open_timeout=OPEN_TIMEOUT_S, close_timeout=CLOSE_TIMEOUT_S):
            pass
        with connect(car.drive.uri, open_timeout=OPEN_TIMEOUT_S, close_timeout=CLOSE_TIMEOUT_S) as drive:
            delay = _command_delay(dut, drive, stalled_command_value)
    finally:
        _close_in_background(stalled)

    assert delay < COMMAND_DELAY_BUDGET_S, (
        f'drive command took {delay:.2f}s to reach the car while the {endpoint_of(car).path} client had stopped reading'
    )
