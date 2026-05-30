import asyncio
import base64
import json
import time

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
