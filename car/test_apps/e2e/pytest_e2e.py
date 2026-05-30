import asyncio
import json
import time

import websockets
from pytest_embedded import Dut

from helpers import get_dut_ip

# Command constants mirrored from motor.hpp
COMMAND_ADVANCE = 1
COMMAND_RETREAT = 2
COMMAND_BRAKE = 3
COMMAND_TURN_LEFT = 4
COMMAND_TURN_RIGHT = 5
COMMAND_LOOK_HORIZONTALLY = 6
COMMAND_LOOK_VERTICALLY = 7


def test_advance_and_brake(dut: Dut) -> None:
    """Advance at 50% for 1 s, verify speed > 0, then brake and verify speed ≈ 0."""
    ip = get_dut_ip(dut)
    dut.expect(r'Starting telemetry task', timeout=30)

    async def run():
        async with websockets.connect(f'ws://{ip}/') as cmd_ws, \
                   websockets.connect(f'ws://{ip}/telemetry') as tel_ws:

            await cmd_ws.send(json.dumps({"command": COMMAND_ADVANCE, "value": 50}))

            speeds_during = []
            for _ in range(3):
                pkt = json.loads(await asyncio.wait_for(tel_ws.recv(), timeout=5))
                speeds_during.append(pkt['speed'])

            await cmd_ws.send(json.dumps({"command": COMMAND_BRAKE, "value": 0}))

            speeds_after = []
            for _ in range(2):
                pkt = json.loads(await asyncio.wait_for(tel_ws.recv(), timeout=5))
                speeds_after.append(pkt['speed'])

        return speeds_during, speeds_after

    speeds_during, speeds_after = asyncio.run(run())
    assert max(speeds_during) > 0, 'speed never exceeded 0 while advancing'
    assert max(speeds_after) < 1.0, \
        f'speed still {max(speeds_after):.2f} km/h after brake'


def test_concurrent_stream_and_telemetry(dut: Dut) -> None:
    """Both /stream and /telemetry deliver data concurrently without starving each other.

    Regression test for the streaming deadlock where the camera stream task
    blocked the telemetry path under concurrent load.
    """
    ip = get_dut_ip(dut)
    dut.expect(r'Starting telemetry task', timeout=30)

    async def run():
        async with websockets.connect(f'ws://{ip}/stream') as stream_ws, \
                   websockets.connect(f'ws://{ip}/telemetry') as tel_ws:

            stream_count = 0
            tel_count = 0
            deadline = time.monotonic() + 10.0

            # Track tasks by WebSocket identity to avoid concurrent recv() on the
            # same connection (ConcurrencyError). Only recreate a task when it completes.
            task_info: dict = {}
            t = asyncio.ensure_future(stream_ws.recv())
            task_info[t] = (stream_ws, 'stream')
            t = asyncio.ensure_future(tel_ws.recv())
            task_info[t] = (tel_ws, 'tel')

            while time.monotonic() < deadline:
                done, _ = await asyncio.wait(
                    list(task_info.keys()),
                    timeout=2.0,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    ws, kind = task_info.pop(task)
                    if kind == 'stream':
                        stream_count += 1
                    else:
                        tel_count += 1
                    new_task = asyncio.ensure_future(ws.recv())
                    task_info[new_task] = (ws, kind)

            for task in task_info:
                task.cancel()

        return stream_count, tel_count

    stream_count, tel_count = asyncio.run(run())
    assert stream_count >= 3, \
        f'stream delivered only {stream_count} frames in 10 s'
    assert tel_count >= 3, \
        f'telemetry delivered only {tel_count} packets in 10 s'


def test_pan_tilt(dut: Dut) -> None:
    """Pan and tilt servo commands complete without WebSocket disconnect or error log."""
    ip = get_dut_ip(dut)

    async def run():
        async with websockets.connect(f'ws://{ip}/') as ws:
            for cmd, value in [
                (COMMAND_LOOK_HORIZONTALLY,  90),
                (COMMAND_LOOK_HORIZONTALLY, -90),
                (COMMAND_LOOK_HORIZONTALLY,   0),
                (COMMAND_LOOK_VERTICALLY,    45),
                (COMMAND_LOOK_VERTICALLY,     0),
            ]:
                await ws.send(json.dumps({"command": cmd, "value": value}))
                await asyncio.sleep(0.5)

    asyncio.run(run())
    dut.expect(r'JSON=\{"command": 6', timeout=3)
