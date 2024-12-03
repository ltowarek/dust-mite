import datetime
import os
import time

import pytest
from websockets.asyncio.client import connect

TELEMETRY_ADDRESS = os.getenv("ESP32_ADDRESS", "ws://localhost") + "/telemetry"

skip_dut_test = pytest.mark.skip(reason="DUT test")


@skip_dut_test
@pytest.mark.asyncio
async def test_performance() -> None:
    packet_count = 100
    async with connect(TELEMETRY_ADDRESS) as websocket:
        start = time.time()
        for _ in range(packet_count):
            await websocket.recv()
        end = time.time()
    duration = datetime.timedelta(seconds=end - start)
    pps = packet_count / duration.total_seconds()

    expected = 1300
    assert pps >= expected


@skip_dut_test
@pytest.mark.asyncio
async def test_latency() -> None:
    async with connect(TELEMETRY_ADDRESS) as websocket:
        pong_waiter = websocket.ping()
        latency_future = await pong_waiter
        latency = await latency_future

    latency_ms = datetime.timedelta(seconds=latency) / datetime.timedelta(
        milliseconds=1
    )
    expected = 60
    assert latency_ms <= expected
