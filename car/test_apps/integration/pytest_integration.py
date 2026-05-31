import asyncio
import base64
import json
import time

import pytest
import websockets
from pytest_embedded import Dut

from helpers import get_dut_ip


def test_command_pipeline(dut: Dut) -> None:
    """Command JSON -> web server -> command queue -> motor task."""
    ip = get_dut_ip(dut)

    async def run():
        async with websockets.connect(f'ws://{ip}/') as ws:
            await ws.send(json.dumps({"command": 3, "value": 0}))

    asyncio.run(run())
    dut.expect(r'JSON=\{"command": 3, "value": 0\}', timeout=5)


def test_telemetry_disconnect(dut: Dut) -> None:
    """Clean disconnect from /telemetry must not produce send errors in the firmware.

    Regression test for the stale-notification + wrong-signal-order bug:
    when the client sends WS CLOSE + TCP FIN while the firmware BG task is still
    writing, Python's TCP stack RSTs the connection on the next firmware write
    (ECONNRESET). The handler then processes the queued CLOSE frame. Before the
    fix it consumed a stale notification and tried to send CLOSE on the dead
    socket, logging an ERROR. After the fix it handles this gracefully.
    """
    ip = get_dut_ip(dut)
    dut.expect(r'Set system time', timeout=60)   # wait for SNTP — this is the bottleneck
    dut.expect(r'Starting telemetry task', timeout=5)  # follows immediately after SNTP

    async def run():
        async with websockets.connect(f'ws://{ip}/telemetry') as ws:
            for _ in range(5):
                await asyncio.wait_for(ws.recv(), timeout=5.0)
        # async-with exit sends WS CLOSE + TCP FIN while the BG task is still
        # sending — firmware's next write gets RST from Python's TCP stack.

    asyncio.run(run())

    # Wait until the CLOSE handler begins — serial data before this point
    # (e.g. the BG task's own ECONNRESET log) is consumed and irrelevant.
    dut.expect(r'Got a WS CLOSE frame', timeout=5)

    # After the CLOSE handler starts, it must not produce an ERROR-level send
    # failure. Before the fix the handler tries to send CLOSE on the dead socket
    # and logs at ERROR level. After the fix it logs at WARN level and returns OK.
    with pytest.raises(Exception):
        dut.expect(r'E \(\d+\) web_server: httpd_ws_send_frame failed', timeout=3)


def test_telemetry_pipeline(dut: Dut) -> None:
    """Sensors -> telemetry task -> web server -> WebSocket client."""
    ip = get_dut_ip(dut)
    dut.expect(r'Starting telemetry task', timeout=30)

    async def run():
        packets = []
        async with websockets.connect(f'ws://{ip}/telemetry') as ws:
            for _ in range(3):
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                packets.append(json.loads(raw))
        return packets

    packets = asyncio.run(run())
    assert len(packets) == 3

    required = {'timestamp', 'rssi', 'speed', 'accelerometer',
                'magnetometer', 'gyroscope', 'distance_ahead'}
    for pkt in packets:
        assert required <= pkt.keys(), f'missing keys: {required - pkt.keys()}'
        for vec in ('accelerometer', 'magnetometer', 'gyroscope'):
            assert {'x', 'y', 'z'} <= pkt[vec].keys()

    timestamps = [pkt['timestamp'] for pkt in packets]
    assert all(isinstance(ts, str) and len(ts) > 0 for ts in timestamps), \
        'timestamps must be non-empty strings'


def test_stream_pipeline(dut: Dut) -> None:
    """Camera -> frame queue -> web server -> Base64 JPEG WebSocket frames."""
    dut.expect(r'Starting camera task', timeout=10)
    ip = get_dut_ip(dut)
    frame_count = 10

    async def run():
        frames = []
        start = time.monotonic()
        async with websockets.connect(f'ws://{ip}/stream') as ws:
            while len(frames) < frame_count:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                frames.append(base64.b64decode(json.loads(raw)['data']))
        elapsed = time.monotonic() - start
        return frames, elapsed

    frames, elapsed = asyncio.run(run())

    for i, frame in enumerate(frames):
        assert frame[:2] == b'\xff\xd8', f'frame {i}: missing JPEG SOI'
        assert frame[-2:] == b'\xff\xd9', f'frame {i}: missing JPEG EOI'
