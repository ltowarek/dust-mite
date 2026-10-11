import asyncio
import json
import socket
import threading
import time

import pytest
import websockets
from pytest_embedded import Dut
from websockets.sync.client import connect

CLOSE_TIMEOUT_S = 10.0

BRAKE = 3

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


def _connect_through_small_window(host: str, port: int, path: str, rcvbuf_bytes: int):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf_bytes)
    sock.settimeout(8)
    sock.connect((host, port))
    return connect(
        f'ws://{host}:{port}{path}', sock=sock, open_timeout=8, close_timeout=CLOSE_TIMEOUT_S, max_queue=1
    )


def _expect_brake(dut: Dut, value: int, timeout: float) -> None:
    dut.expect(rf'JSON=\{{"command": {BRAKE}, "value": {value}\}}', timeout=timeout)


def test_unity_cases_pass(dut: Dut) -> None:
    dut.run_all_single_board_cases(reset=True, timeout=60)


def test_web_server_endpoints_reachable(dut: Dut, car_address: tuple[str, int]) -> None:
    host, port = car_address

    async def run():
        async with websockets.connect(f'ws://{host}:{port}/') as ws:
            pass
        async with websockets.connect(f'ws://{host}:{port}/telemetry') as ws:
            pass
        async with websockets.connect(f'ws://{host}:{port}/stream') as ws:
            pass

    asyncio.run(run())


@pytest.mark.dut(reason=_SLOW_CLIENT_REASON)
def test_command_not_delayed_by_slow_stream_reader(dut: Dut, car_address: tuple[str, int]) -> None:
    command_count = 150
    command_interval_s = 0.1
    command_delay_budget_s = 1.0
    slow_read_interval_s = 0.3
    slow_read_rcvbuf_bytes = 8192
    host, port = car_address

    stream = _connect_through_small_window(host, port, '/stream', slow_read_rcvbuf_bytes)
    stop = threading.Event()

    def _read_slowly() -> None:
        while not stop.is_set():
            stream.recv(timeout=8)
            stop.wait(slow_read_interval_s)

    reader = threading.Thread(target=_read_slowly, daemon=True)
    reader.start()

    control = connect(f'ws://{host}:{port}/', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
    sent_at: dict[int, float] = {}

    def _send_commands() -> None:
        for value in range(command_count):
            sent_at[value] = time.monotonic()
            control.send(json.dumps({'command': BRAKE, 'value': value}))
            time.sleep(command_interval_s)

    sender = threading.Thread(target=_send_commands, daemon=True)
    sender.start()

    delays = []
    try:
        for value in range(command_count):
            _expect_brake(dut, value, timeout=15)
            delays.append(time.monotonic() - sent_at[value])
    finally:
        stop.set()
        sender.join(timeout=command_count * command_interval_s + 5)
        _close_in_background(control)
        _close_in_background(stream)

    worst = max(delays)
    assert worst < command_delay_budget_s, (
        f'drive command took {worst:.2f}s to reach the car while /stream was read slowly; '
        f'commands are queued behind camera frames on the httpd task (delays: {delays})'
    )


@pytest.mark.dut(reason=_SLOW_CLIENT_REASON)
def test_command_still_read_after_close_while_telemetry_send_stalls(dut: Dut, car_address: tuple[str, int]) -> None:
    stalled_rcvbuf_bytes = 1024
    stall_settle_s = 60.0
    stalled_open_timeout_s = 30.0
    stalled_command_budget_s = 30.0
    stalled_command_value = 7
    host, port = car_address

    stalled = _connect_through_small_window(host, port, '/telemetry', stalled_rcvbuf_bytes)
    time.sleep(stall_settle_s)

    try:
        with connect(f'ws://{host}:{port}/', open_timeout=stalled_open_timeout_s, close_timeout=CLOSE_TIMEOUT_S):
            pass
        with connect(
            f'ws://{host}:{port}/', open_timeout=stalled_open_timeout_s, close_timeout=CLOSE_TIMEOUT_S
        ) as control:
            control.send(json.dumps({'command': BRAKE, 'value': stalled_command_value}))
            _expect_brake(dut, stalled_command_value, timeout=stalled_command_budget_s)
    finally:
        _close_in_background(stalled)
