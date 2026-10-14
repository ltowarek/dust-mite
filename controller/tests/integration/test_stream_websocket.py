import datetime
import time

import pytest
from websockets.asyncio.client import connect

from controller.streamer import StreamerSettings


@pytest.fixture
def stream_client_uri(streamer_settings: StreamerSettings) -> str:
    return streamer_settings.camera_uri


@pytest.mark.dut
@pytest.mark.asyncio
async def test_performance(stream_client_uri: str) -> None:
    frame_count = 100
    async with connect(stream_client_uri) as websocket:
        start = time.time()
        for _ in range(frame_count):
            await websocket.recv()
        end = time.time()
    duration = datetime.timedelta(seconds=end - start)
    fps = frame_count / duration.total_seconds()

    # Camera itself reaches 25 FPS so we are loosing 1-3 FPS through network
    expected = 22
    assert fps >= expected


@pytest.mark.dut
@pytest.mark.asyncio
async def test_latency(stream_client_uri: str) -> None:
    async with connect(stream_client_uri) as websocket:
        pong_waiter = websocket.ping()
        latency_future = await pong_waiter
        latency = await latency_future

    latency_ms = datetime.timedelta(seconds=latency) / datetime.timedelta(
        milliseconds=1
    )
    expected = 60
    assert latency_ms <= expected
