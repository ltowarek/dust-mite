import datetime
import os
import time

import pytest
from websockets.asyncio.client import connect

STREAM_ADDRESS = os.environ["ESP32_ADDRESS"] + "/stream"

skip_dut_test = pytest.mark.skip(reason="DUT test")


@skip_dut_test
@pytest.mark.asyncio
async def test_performance() -> None:
    measurements = 100
    async with connect(STREAM_ADDRESS) as websocket:
        start = time.time()
        for _ in range(measurements):
            await websocket.recv()
        end = time.time()
    duration = datetime.timedelta(seconds=end - start)
    fps = measurements / duration.total_seconds()

    # Camera itself reaches 25 FPS so we are loosing 1-3 FPS through network
    expected = 22
    assert fps >= expected
