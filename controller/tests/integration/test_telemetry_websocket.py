import datetime
import os
import time

import pytest
from websockets.asyncio.client import connect

skip_dut_test = pytest.mark.skip(reason="DUT test")


@pytest.fixture
def telemetry_client_uri() -> str:
    return os.environ.get("TELEMETRY_CLIENT_URI", "ws://localhost:8765/telemetry")


@skip_dut_test
@pytest.mark.asyncio
async def test_performance(telemetry_client_uri: str) -> None:
    packet_count = 100
    async with connect(telemetry_client_uri) as websocket:
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
async def test_latency(telemetry_client_uri: str) -> None:
    async with connect(telemetry_client_uri) as websocket:
        pong_waiter = websocket.ping()
        latency_future = await pong_waiter
        latency = await latency_future

    latency_ms = datetime.timedelta(seconds=latency) / datetime.timedelta(
        milliseconds=1
    )
    expected = 60
    assert latency_ms <= expected
