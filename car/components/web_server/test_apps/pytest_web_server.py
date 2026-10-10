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
from helpers import get_dut_ip
from pytest_embedded import Dut
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

CLOSE_BUDGET_S = 2.0
CLOSE_TIMEOUT_S = 10.0
FIRST_FRAME_BUDGET_S = 2.0
BUSY_RETRY_INTERVAL_S = 0.1

BRAKE = 3
COMMAND_COUNT = 150
COMMAND_INTERVAL_S = 0.1
COMMAND_DELAY_BUDGET_S = 1.0
SLOW_READ_INTERVAL_S = 0.3
SLOW_READ_RCVBUF_BYTES = 8192
STALLED_RCVBUF_BYTES = 1024
STALL_SETTLE_S = 60.0
STALLED_OPEN_TIMEOUT_S = 20.0
STALLED_COMMAND_BUDGET_S = 20.0
STALLED_COMMAND_VALUE = 7


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


def _connect_when_free(url: str):
    """Each endpoint serves one connection and refuses others with 503, so a reconnect retries
    until the car has processed the previous connection's close."""
    deadline = time.monotonic() + CLOSE_TIMEOUT_S
    while True:
        try:
            return connect(url, open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
        except InvalidStatus as e:
            if not _is_busy(e) or time.monotonic() > deadline:
                raise
            time.sleep(BUSY_RETRY_INTERVAL_S)


def test_web_server_endpoints_reachable(dut: Dut) -> None:
    ip = get_dut_ip(dut)

    async def run():
        async with websockets.connect(f'ws://{ip}/') as ws:
            pass
        async with websockets.connect(f'ws://{ip}/telemetry') as ws:
            pass
        async with websockets.connect(f'ws://{ip}/stream') as ws:
            pass

    asyncio.run(run())


def test_stream_close_handshake_completes_promptly(dut: Dut) -> None:
    ip = get_dut_ip(dut)

    ws = connect(f'ws://{ip}/stream', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
    for _ in range(5):
        ws.recv(timeout=8)

    done, started = _close_in_background(ws)
    replied = done.wait(CLOSE_BUDGET_S)
    elapsed = time.monotonic() - started

    assert replied, (
        f'server did not reply to CLOSE within {CLOSE_BUDGET_S}s (waited {elapsed:.1f}s); '
        'the streaming task is not servicing inbound frames'
    )


def test_stream_reconnect_receives_data_while_previous_closes(dut: Dut) -> None:
    ip = get_dut_ip(dut)

    first = connect(f'ws://{ip}/stream', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
    for _ in range(5):
        first.recv(timeout=8)
    _close_in_background(first)

    second = _connect_when_free(f'ws://{ip}/stream')
    try:
        frame = second.recv(timeout=FIRST_FRAME_BUDGET_S)
    finally:
        _close_in_background(second)

    assert frame, 'reconnected /stream produced no frame'


def test_stream_survives_connect_close_churn(dut: Dut) -> None:
    ip = get_dut_ip(dut)

    churned = []
    for _ in range(6):
        try:
            ws = connect(f'ws://{ip}/stream', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
        except InvalidStatus as e:
            assert _is_busy(e), f'churned /stream refused with {e.response.status_code}'
            continue
        churned.append((ws, _close_in_background(ws)[0]))

    with _connect_when_free(f'ws://{ip}/stream') as ws:
        assert ws.recv(timeout=FIRST_FRAME_BUDGET_S), 'no frame after connect/close churn'

    for ws, done in churned:
        assert done.wait(CLOSE_TIMEOUT_S + CLOSE_BUDGET_S), 'churned /stream close did not finish'
    unanswered = sum(ws.protocol.close_rcvd is None for ws, _ in churned)
    assert unanswered == 0, (
        f'{unanswered} of {len(churned)} churned /stream connections were dropped without a CLOSE reply'
    )


def test_stream_recovers_after_lru_purge(dut: Dut) -> None:
    ip = get_dut_ip(dut)

    held = [
        connect(f'ws://{ip}{path}', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
        for path in ('/', '/telemetry', '/stream')
    ]
    fourth = connect(f'ws://{ip}/', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
    for ws in [*held, fourth]:
        _close_in_background(ws)

    with _connect_when_free(f'ws://{ip}/stream') as ws:
        assert ws.recv(timeout=FIRST_FRAME_BUDGET_S), 'no frame after an LRU purge'


def test_stream_answers_ping_mid_stream(dut: Dut) -> None:
    ip = get_dut_ip(dut)

    async def run() -> int:
        frames = 0
        async with websockets.connect(
            f'ws://{ip}/stream', open_timeout=8, ping_interval=2, ping_timeout=6
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


def test_command_not_delayed_by_slow_stream_reader(dut: Dut) -> None:
    ip = get_dut_ip(dut)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, SLOW_READ_RCVBUF_BYTES)
    sock.settimeout(8)
    sock.connect((ip, 80))
    stream = connect(
        f'ws://{ip}/stream', sock=sock, open_timeout=8, close_timeout=CLOSE_TIMEOUT_S, max_queue=1
    )
    stop = threading.Event()

    def _read_slowly() -> None:
        while not stop.is_set():
            stream.recv(timeout=8)
            stop.wait(SLOW_READ_INTERVAL_S)

    reader = threading.Thread(target=_read_slowly, daemon=True)
    reader.start()

    control = connect(f'ws://{ip}/', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
    sent_at: dict[int, float] = {}

    def _send_commands() -> None:
        for value in range(COMMAND_COUNT):
            sent_at[value] = time.monotonic()
            control.send(json.dumps({'command': BRAKE, 'value': value}))
            time.sleep(COMMAND_INTERVAL_S)

    sender = threading.Thread(target=_send_commands, daemon=True)
    sender.start()

    delays = []
    try:
        for value in range(COMMAND_COUNT):
            dut.expect(rf'JSON=\{{"command": {BRAKE}, "value": {value}\}}', timeout=15)
            delays.append(time.monotonic() - sent_at[value])
    finally:
        stop.set()
        sender.join(timeout=COMMAND_COUNT * COMMAND_INTERVAL_S + 5)
        _close_in_background(control)
        _close_in_background(stream)

    worst = max(delays)
    assert worst < COMMAND_DELAY_BUDGET_S, (
        f'drive command took {worst:.2f}s to reach the car while /stream was read slowly; '
        f'commands are queued behind camera frames on the httpd task (delays: {delays})'
    )


@pytest.mark.parametrize('path', ['/stream', '/telemetry'])
def test_second_connection_refused_before_upgrade(dut: Dut, path: str) -> None:
    ip = get_dut_ip(dut)

    served = connect(f'ws://{ip}{path}', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
    try:
        for _ in range(2):
            with pytest.raises(InvalidStatus) as refused:
                connect(f'ws://{ip}{path}', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
            assert _is_busy(refused.value), (
                f'second {path} got {refused.value.response.status_code}, not 503'
            )
    finally:
        done, _ = _close_in_background(served)
    assert done.wait(CLOSE_TIMEOUT_S + CLOSE_BUDGET_S), f'served {path} close did not finish'

    with _connect_when_free(f'ws://{ip}{path}'):
        pass


def test_command_still_read_after_close_while_telemetry_send_stalls(dut: Dut) -> None:
    ip = get_dut_ip(dut)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, STALLED_RCVBUF_BYTES)
    sock.settimeout(8)
    sock.connect((ip, 80))
    stalled = connect(
        f'ws://{ip}/telemetry', sock=sock, open_timeout=8, close_timeout=CLOSE_TIMEOUT_S, max_queue=1
    )
    time.sleep(STALL_SETTLE_S)

    try:
        with connect(f'ws://{ip}/', open_timeout=STALLED_OPEN_TIMEOUT_S, close_timeout=CLOSE_TIMEOUT_S):
            pass
        with connect(
            f'ws://{ip}/', open_timeout=STALLED_OPEN_TIMEOUT_S, close_timeout=CLOSE_TIMEOUT_S
        ) as control:
            control.send(json.dumps({'command': BRAKE, 'value': STALLED_COMMAND_VALUE}))
            dut.expect(
                rf'JSON=\{{"command": {BRAKE}, "value": {STALLED_COMMAND_VALUE}\}}',
                timeout=STALLED_COMMAND_BUDGET_S,
            )
    finally:
        _close_in_background(stalled)
