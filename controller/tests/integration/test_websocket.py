import datetime
import os
import time

import pytest
from websockets.asyncio.client import connect

STREAM_ADDRESS = os.getenv("ESP32_ADDRESS", "ws://localhost") + "/stream"

skip_dut_test = pytest.mark.skip(reason="DUT test")


@skip_dut_test
@pytest.mark.asyncio
async def test_performance() -> None:
    frame_count = 100
    async with connect(STREAM_ADDRESS) as websocket:
        start = time.time()
        for _ in range(frame_count):
            await websocket.recv()
        end = time.time()
    duration = datetime.timedelta(seconds=end - start)
    fps = frame_count / duration.total_seconds()

    # Camera itself reaches 25 FPS so we are loosing 1-3 FPS through network
    expected = 22
    assert fps >= expected


@skip_dut_test
@pytest.mark.asyncio
async def test_latency() -> None:
    async with connect(STREAM_ADDRESS) as websocket:
        pong_waiter = websocket.ping()
        latency_future = await pong_waiter
        latency = await latency_future

    latency_ms = datetime.timedelta(seconds=latency) / datetime.timedelta(
        milliseconds=1
    )
    expected = 60
    assert latency_ms <= expected
