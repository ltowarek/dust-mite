import asyncio
import json
import math
import time
from collections.abc import Callable
from operator import attrgetter

import pytest
import websockets
from pytest_embedded import Dut

from helpers import CarEndpoints, Endpoint, car_endpoints, get_dut_ip

# Command constants mirrored from motor.hpp
COMMAND_ADVANCE = 1
COMMAND_RETREAT = 2
COMMAND_BRAKE = 3
COMMAND_TURN_LEFT = 4
COMMAND_TURN_RIGHT = 5
COMMAND_LOOK_HORIZONTALLY = 6
COMMAND_LOOK_VERTICALLY = 7

HTTP_SERVICE_UNAVAILABLE = 503

# Mirrored from DRIVE_COMMAND_WATCHDOG_MS in motor.cpp
DRIVE_COMMAND_WATCHDOG_MS = 1000


_ENDPOINTS = [pytest.param(attrgetter(name), id=name) for name in ('drive', 'camera', 'telemetry')]


async def _connect_twice(endpoint: Endpoint) -> tuple[int | None, bool]:
    """Holds one connection, tries a second, and returns the second's refusal status and whether the first
    still answers a ping afterwards. No command frames are sent, so the car does not move."""
    async with websockets.connect(endpoint.uri) as first:
        try:
            async with websockets.connect(endpoint.uri):
                status = None
        except websockets.InvalidStatus as e:
            status = e.response.status_code
        try:
            await asyncio.wait_for(await first.ping(), timeout=5)
        except (websockets.ConnectionClosed, TimeoutError):
            return status, False
    return status, True


@pytest.mark.parametrize('endpoint_of', _ENDPOINTS)
def test_second_connection_refused_before_upgrade(dut: Dut, endpoint_of: Callable[[CarEndpoints], Endpoint]) -> None:
    """Each endpoint serves one client and refuses a second with 503 before the WebSocket upgrade."""
    endpoint = endpoint_of(car_endpoints(get_dut_ip(dut)))
    dut.expect(r'Serving every endpoint', timeout=70)

    status, _ = asyncio.run(_connect_twice(endpoint))

    assert status == HTTP_SERVICE_UNAVAILABLE


@pytest.mark.parametrize('endpoint_of', _ENDPOINTS)
def test_first_connection_stays_open_after_second_is_refused(
    dut: Dut, endpoint_of: Callable[[CarEndpoints], Endpoint]
) -> None:
    endpoint = endpoint_of(car_endpoints(get_dut_ip(dut)))
    dut.expect(r'Serving every endpoint', timeout=70)

    _, first_open = asyncio.run(_connect_twice(endpoint))

    assert first_open, f'refusing a second connection to {endpoint.path} closed the first one'


def test_advance_and_brake(dut: Dut) -> None:
    """Advance at 50%, resent like a browser's 10 Hz stream, verify speed > 0, then brake.

    ADVANCE is resent every 100 ms (well under the drive command watchdog)
    for the duration of the sampling window, mirroring the continuous stream
    the browser sends while a key/stick is held. A single ADVANCE would race
    the watchdog: telemetry emits every 500 ms, so the car could already have
    self-braked before enough samples arrived.
    """
    car = car_endpoints(get_dut_ip(dut))
    dut.expect(r'Serving every endpoint', timeout=70)

    async def run():
        async with websockets.connect(car.drive.uri) as cmd_ws, \
                   websockets.connect(car.telemetry.uri) as tel_ws:

            stop_resend = asyncio.Event()

            async def resend_advance():
                while not stop_resend.is_set():
                    await cmd_ws.send(json.dumps({"command": COMMAND_ADVANCE, "value": 50}))
                    await asyncio.sleep(0.1)

            resend_task = asyncio.ensure_future(resend_advance())

            speeds_during = []
            for _ in range(3):
                pkt = json.loads(await asyncio.wait_for(tel_ws.recv(), timeout=5))
                speeds_during.append(pkt['speed'])

            stop_resend.set()
            await resend_task

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


def test_watchdog_brakes_without_explicit_brake(dut: Dut) -> None:
    """A single ADVANCE with no follow-up command is braked by the firmware watchdog.

    Regression test for a dropped or lost BRAKE, or a sender that dies mid-drive:
    the car must not keep driving indefinitely just because nothing told it to stop.
    """
    car = car_endpoints(get_dut_ip(dut))
    dut.expect(r'Serving every endpoint', timeout=70)

    async def run():
        async with websockets.connect(car.drive.uri) as cmd_ws, \
                   websockets.connect(car.telemetry.uri) as tel_ws:

            await cmd_ws.send(json.dumps({"command": COMMAND_ADVANCE, "value": 50}))

            # No further commands sent. Telemetry emits every 500 ms; wait past
            # the watchdog interval with margin so the last sample must show a
            # braked car regardless of exactly when in its cycle ADVANCE landed.
            samples = math.ceil(DRIVE_COMMAND_WATCHDOG_MS / 500) + 1
            speeds = []
            for _ in range(samples):
                pkt = json.loads(await asyncio.wait_for(tel_ws.recv(), timeout=5))
                speeds.append(pkt['speed'])

        return speeds

    speeds = asyncio.run(run())
    assert speeds[-1] < 1.0, \
        f'speed still {speeds[-1]:.2f} km/h after a single ADVANCE with no follow-up command'


def test_look_does_not_reset_drive_watchdog(dut: Dut) -> None:
    """LOOK_* commands must not keep a stale drive command alive past the watchdog.

    A stream of pan/tilt commands carries no drive intent, so it must not
    reset the drive command watchdog deadline.
    """
    car = car_endpoints(get_dut_ip(dut))
    dut.expect(r'Serving every endpoint', timeout=70)

    async def run():
        async with websockets.connect(car.drive.uri) as cmd_ws, \
                   websockets.connect(car.telemetry.uri) as tel_ws:

            await cmd_ws.send(json.dumps({"command": COMMAND_ADVANCE, "value": 50}))

            # Send LOOK_* well past the watchdog interval, with no drive resend.
            deadline = time.monotonic() + 3 * DRIVE_COMMAND_WATCHDOG_MS / 1000
            while time.monotonic() < deadline:
                await cmd_ws.send(json.dumps({"command": COMMAND_LOOK_HORIZONTALLY, "value": 0}))
                await asyncio.sleep(0.1)

            pkt = json.loads(await asyncio.wait_for(tel_ws.recv(), timeout=5))

        return pkt['speed']

    speed = asyncio.run(run())
    assert speed < 1.0, \
        f'speed still {speed:.2f} km/h after LOOK_* commands with no drive resend'


def test_concurrent_stream_and_telemetry(dut: Dut) -> None:
    """Both /stream and /telemetry deliver data concurrently without starving each other.

    Regression test for the streaming deadlock where the camera stream task
    blocked the telemetry path under concurrent load.
    """
    car = car_endpoints(get_dut_ip(dut))
    dut.expect(r'Serving every endpoint', timeout=70)

    async def run():
        async with websockets.connect(car.camera.uri) as stream_ws, \
                   websockets.connect(car.telemetry.uri) as tel_ws:

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
    car = car_endpoints(get_dut_ip(dut))
    dut.expect(r'Serving every endpoint', timeout=70)

    async def run():
        async with websockets.connect(car.drive.uri) as ws:
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
