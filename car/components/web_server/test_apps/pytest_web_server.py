import asyncio
import base64
import json
import os
import socket
import struct
import threading
import time

import websockets
from helpers import get_dut_ip
from pytest_embedded import Dut
from websockets.sync.client import connect

CLOSE_BUDGET_S = 2.0
CLOSE_TIMEOUT_S = 10.0
FIRST_FRAME_BUDGET_S = 2.0


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

    second = connect(f'ws://{ip}/stream', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
    try:
        frame = second.recv(timeout=FIRST_FRAME_BUDGET_S)
    finally:
        _close_in_background(second)

    assert frame, 'reconnected /stream produced no frame'


def test_stream_survives_connect_close_churn(dut: Dut) -> None:
    ip = get_dut_ip(dut)

    for _ in range(6):
        ws = connect(f'ws://{ip}/stream', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
        _close_in_background(ws)

    with connect(f'ws://{ip}/stream', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S) as ws:
        assert ws.recv(timeout=FIRST_FRAME_BUDGET_S), 'no frame after connect/close churn'


def test_stream_recovers_after_lru_purge(dut: Dut) -> None:
    ip = get_dut_ip(dut)

    held = [
        connect(f'ws://{ip}{path}', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
        for path in ('/', '/telemetry', '/stream')
    ]
    fourth = connect(f'ws://{ip}/', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S)
    for ws in [*held, fourth]:
        _close_in_background(ws)

    with connect(f'ws://{ip}/stream', open_timeout=8, close_timeout=CLOSE_TIMEOUT_S) as ws:
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
