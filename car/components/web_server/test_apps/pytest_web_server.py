import asyncio
import base64
import json
import os
import socket
import struct
import threading
import time

import pytest
import websockets
from pytest_embedded import Dut
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

CLOSE_BUDGET_S = 2.0
CLOSE_TIMEOUT_S = 10.0
FIRST_FRAME_BUDGET_S = 2.0

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


def _is_busy(error: InvalidStatus) -> bool:
    return error.response.status_code == 503


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


def _connect_when_free(url: str):
    """Each endpoint serves one connection and refuses others with 503, so a reconnect retries
    until the car has processed the previous connection's close."""
    busy_retry_interval_s = 0.1
    deadline = time.monotonic() + CLOSE_TIMEOUT_S
    while True:
        try:
            return connect(url, open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
        except InvalidStatus as e:
            if not _is_busy(e) or time.monotonic() > deadline:
                raise
            time.sleep(busy_retry_interval_s)


def test_unit_tests_pass(dut: Dut) -> None:
    dut.expect_unity_test_output()


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


def test_stream_close_handshake_completes_promptly(dut: Dut, car_address: tuple[str, int]) -> None:
    host, port = car_address

    ws = connect(f'ws://{host}:{port}/stream', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
    for _ in range(5):
        ws.recv(timeout=8)

    done, started = _close_in_background(ws)
    replied = done.wait(CLOSE_BUDGET_S)
    elapsed = time.monotonic() - started

    assert replied, (
        f'server did not reply to CLOSE within {CLOSE_BUDGET_S}s (waited {elapsed:.1f}s); '
        'the streaming task is not servicing inbound frames'
    )


def test_stream_reconnect_receives_data_while_previous_closes(dut: Dut, car_address: tuple[str, int]) -> None:
    host, port = car_address

    first = connect(f'ws://{host}:{port}/stream', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
    for _ in range(5):
        first.recv(timeout=8)
    _close_in_background(first)

    second = _connect_when_free(f'ws://{host}:{port}/stream')
    try:
        frame = second.recv(timeout=FIRST_FRAME_BUDGET_S)
    finally:
        _close_in_background(second)

    assert frame, 'reconnected /stream produced no frame'


def test_stream_survives_connect_close_churn(dut: Dut, car_address: tuple[str, int]) -> None:
    host, port = car_address

    churned = []
    for _ in range(6):
        try:
            ws = connect(f'ws://{host}:{port}/stream', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
        except InvalidStatus as e:
            assert _is_busy(e), f'churned /stream refused with {e.response.status_code}'
            continue
        churned.append((ws, _close_in_background(ws)[0]))

    with _connect_when_free(f'ws://{host}:{port}/stream') as ws:
        assert ws.recv(timeout=FIRST_FRAME_BUDGET_S), 'no frame after connect/close churn'

    for ws, done in churned:
        assert done.wait(CLOSE_TIMEOUT_S + CLOSE_BUDGET_S), 'churned /stream close did not finish'
    unanswered = sum(ws.protocol.close_rcvd is None for ws, _ in churned)
    assert unanswered == 0, (
        f'{unanswered} of {len(churned)} churned /stream connections were dropped without a CLOSE reply'
    )


def test_stream_recovers_after_lru_purge(dut: Dut, car_address: tuple[str, int]) -> None:
    host, port = car_address

    held = [
        connect(f'ws://{host}:{port}{path}', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
        for path in ('/', '/telemetry', '/stream')
    ]
    fourth = connect(f'ws://{host}:{port}/', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
    for ws in [*held, fourth]:
        _close_in_background(ws)

    with _connect_when_free(f'ws://{host}:{port}/stream') as ws:
        assert ws.recv(timeout=FIRST_FRAME_BUDGET_S), 'no frame after an LRU purge'


def test_stream_answers_ping_mid_stream(dut: Dut, car_address: tuple[str, int]) -> None:
    host, port = car_address

    async def run() -> int:
        frames = 0
        async with websockets.connect(
            f'ws://{host}:{port}/stream', open_timeout=8, ping_interval=2, ping_timeout=6
        ) as ws:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                msg = await asyncio.wait_for(ws.recv(), timeout=8)
                frames += 1
                assert msg.startswith('{') and msg.rstrip().endswith('}'), (
                    f'malformed frame {frames}: {msg[:40]!r}...{msg[-20:]!r}'
                )
        return frames

    assert asyncio.run(run()) > 0, 'no frames received'


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


@pytest.mark.parametrize('path', ['/stream', '/telemetry'])
def test_second_connection_refused_before_upgrade(dut: Dut, car_address: tuple[str, int], path: str) -> None:
    host, port = car_address

    served = connect(f'ws://{host}:{port}{path}', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
    try:
        for _ in range(2):
            with pytest.raises(InvalidStatus) as refused:
                connect(f'ws://{host}:{port}{path}', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
            assert _is_busy(refused.value), (
                f'second {path} got {refused.value.response.status_code}, not 503'
            )
    finally:
        done, _ = _close_in_background(served)
    assert done.wait(CLOSE_TIMEOUT_S + CLOSE_BUDGET_S), f'served {path} close did not finish'

    with _connect_when_free(f'ws://{host}:{port}{path}'):
        pass


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
