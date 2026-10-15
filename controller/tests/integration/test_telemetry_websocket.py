import datetime
import time

import pytest
from websockets.asyncio.client import connect

from controller.streamer import StreamerSettings


@pytest.fixture
def telemetry_client_uri(streamer_settings: StreamerSettings) -> str:
    return streamer_settings.telemetry_uri


@pytest.mark.dut
@pytest.mark.asyncio
async def test_performance(telemetry_client_uri: str) -> None:
    message_count = 100
    async with connect(telemetry_client_uri) as websocket:
        start = time.time()
        for _ in range(message_count):
            await websocket.recv()
        end = time.time()
    duration = datetime.timedelta(seconds=end - start)
    messages_per_second = message_count / duration.total_seconds()

    expected = 1300
    assert messages_per_second >= expected


@pytest.mark.dut
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
