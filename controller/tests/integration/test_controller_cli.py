"""Guards the controller CLI's drive loop against the in-process streamer."""

import asyncio
import contextlib
import dataclasses
import itertools
import logging
import socket
import time
import urllib.parse
from collections.abc import Callable

import pytest
import websockets.asyncio.client

from controller.command import Command, DriveCommand
from controller.controller import DriveConnectionClosedError, drive
from controller.senders import send_command
from controller.streamer import serve_streamer

from .conftest import local_streamer_settings
from .test_doubles import CarEndpointSpy
from .waiting import WAIT_TIMEOUT_S, wait_for

_SPEED = 50


class HeldInputStub:
    """Input backend publishing each Drive command the test holds, until quit."""

    def __init__(self) -> None:
        self._held: DriveCommand = (Command.BRAKE, None)
        self._publish: Callable[[DriveCommand], None] | None = None
        self._quit = asyncio.Event()

    def hold(self, command: Command, value: int | None) -> None:
        self._held = (command, value)
        if self._publish is not None:
            self._publish(self._held)

    def quit(self) -> None:
        self._quit.set()

    async def read(self, publish: Callable[[DriveCommand], None]) -> None:
        self._publish = publish
        publish(self._held)
        await self._quit.wait()


async def _eventually(condition: Callable[[], bool]) -> bool:
    return await asyncio.to_thread(wait_for, condition)


def _received_values(control: CarEndpointSpy) -> list[int]:
    return [command["value"] for command in control.received]


@dataclasses.dataclass(frozen=True)
class HeldThenReleased:
    """What reached the car while the CLI sat parked, held a control, then let go."""

    held_at: float
    arrivals: list[tuple[float, Command]]

    def held(self) -> list[float]:
        return [at for at, command in self.arrivals if command is not Command.BRAKE]


@pytest.fixture
def held_then_released(
    camera_feed: CarEndpointSpy,
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
    caplog: pytest.LogCaptureFixture,
) -> HeldThenReleased:
    return asyncio.run(
        _hold_then_release(camera_feed, telemetry_feed, car_control, caplog)
    )


async def _hold_then_release(
    camera_feed: CarEndpointSpy,
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
    caplog: pytest.LogCaptureFixture,
) -> HeldThenReleased:
    phase_s = 0.5
    inputs = HeldInputStub()
    settings = local_streamer_settings(camera_feed, telemetry_feed, car_control)
    async with asyncio.timeout(WAIT_TIMEOUT_S), serve_streamer(settings) as streamer:
        cli = asyncio.create_task(drive(inputs, streamer.drive))
        await _eventually(lambda: _connected_to(caplog.records, streamer.drive))
        await asyncio.sleep(phase_s)
        held_at = time.monotonic()
        inputs.hold(Command.TURN_LEFT, _SPEED)
        await asyncio.sleep(phase_s)
        inputs.hold(Command.BRAKE, None)
        await asyncio.sleep(phase_s)
        inputs.quit()
        await cli

    arrivals = [
        (at, Command(message["command"]))
        for at, message in zip(
            car_control.received_at, car_control.received, strict=True
        )
    ]
    return HeldThenReleased(held_at, arrivals)


def test_sends_a_held_command_at_once(held_then_released: HeldThenReleased) -> None:
    # Well before the first resend.
    at_once_s = 0.1
    first_s = held_then_released.held()[0] - held_then_released.held_at

    assert first_s < at_once_s


def test_resends_a_held_command(held_then_released: HeldThenReleased) -> None:
    # The 0.5 s hold spans about five sends.
    fewest = 3

    assert len(held_then_released.held()) >= fewest


def test_resends_a_held_command_about_every_100_ms(
    held_then_released: HeldThenReleased,
) -> None:
    shortest_s, longest_s = 0.05, 0.15
    held = held_then_released.held()
    gaps_s = [later - earlier for earlier, later in itertools.pairwise(held)]

    assert all(shortest_s < gap_s < longest_s for gap_s in gaps_s)


def test_sends_one_brake_on_release(held_then_released: HeldThenReleased) -> None:
    commands = [command for _, command in held_then_released.arrivals]

    assert commands.count(Command.BRAKE) == 1


def test_sends_nothing_after_the_brake(
    held_then_released: HeldThenReleased,
) -> None:
    commands = [command for _, command in held_then_released.arrivals]

    assert commands[-1] is Command.BRAKE


def test_sends_nothing_while_parked_before_driving(
    held_then_released: HeldThenReleased,
) -> None:
    before_hold = [
        command
        for at, command in held_then_released.arrivals
        if at < held_then_released.held_at
    ]

    assert before_hold == []


@pytest.mark.asyncio
async def test_drives_the_car_again_after_the_streamer_restarts(
    camera_feed: CarEndpointSpy,
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
) -> None:
    sent_before_restart = 1
    sent_after_restart = 2
    inputs = HeldInputStub()
    settings = local_streamer_settings(camera_feed, telemetry_feed, car_control)
    async with asyncio.timeout(WAIT_TIMEOUT_S):
        async with serve_streamer(settings) as streamer:
            cli = asyncio.create_task(drive(inputs, streamer.drive))
            inputs.hold(Command.ADVANCE, sent_before_restart)
            await _eventually(lambda: bool(car_control.received))
        port = urllib.parse.urlsplit(streamer.drive).port or 0
        restarted = local_streamer_settings(
            camera_feed, telemetry_feed, car_control, websocket_port=port
        )
        async with serve_streamer(restarted):
            inputs.hold(Command.ADVANCE, sent_after_restart)
            await _eventually(
                lambda: sent_after_restart in _received_values(car_control)
            )
            inputs.quit()
            await cli

    assert sent_after_restart in _received_values(car_control)


@pytest.mark.asyncio
async def test_connects_once_the_streamer_comes_up(
    camera_feed: CarEndpointSpy,
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
) -> None:
    inputs = HeldInputStub()
    inputs.hold(Command.ADVANCE, _SPEED)
    async with asyncio.timeout(WAIT_TIMEOUT_S):
        # Holds the port until the CLI's first attempt reaches it.
        with socket.create_server(("127.0.0.1", 0)) as before_the_streamer:
            port = before_the_streamer.getsockname()[1]
            cli = asyncio.create_task(drive(inputs, f"ws://127.0.0.1:{port}/drive"))
            first_attempt, _ = await asyncio.to_thread(before_the_streamer.accept)
            first_attempt.close()
        settings = local_streamer_settings(
            camera_feed, telemetry_feed, car_control, websocket_port=port
        )
        async with serve_streamer(settings):
            await _eventually(lambda: bool(car_control.received))
            inputs.quit()
            await cli

    assert _SPEED in _received_values(car_control)


@pytest.mark.asyncio
async def test_exits_with_the_reason_while_another_driver_holds_drive(
    camera_feed: CarEndpointSpy,
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
) -> None:
    settings = local_streamer_settings(camera_feed, telemetry_feed, car_control)
    async with (
        asyncio.timeout(WAIT_TIMEOUT_S),
        serve_streamer(settings) as streamer,
        websockets.asyncio.client.connect(streamer.drive, proxy=None) as other,
    ):
        await send_command(other, (Command.ADVANCE, _SPEED))
        await _eventually(lambda: bool(car_control.received))
        with pytest.raises(DriveConnectionClosedError, match="another driver"):
            await drive(HeldInputStub(), streamer.drive)


@pytest.mark.asyncio
async def test_exits_with_the_reason_on_a_wrong_path(
    camera_feed: CarEndpointSpy,
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
) -> None:
    settings = local_streamer_settings(camera_feed, telemetry_feed, car_control)
    async with asyncio.timeout(WAIT_TIMEOUT_S), serve_streamer(settings) as streamer:
        wrong_path = urllib.parse.urljoin(streamer.drive, "/")
        with pytest.raises(DriveConnectionClosedError, match="unknown path"):
            await drive(HeldInputStub(), wrong_path)


@pytest.mark.asyncio
async def test_connects_to_a_wrong_path_only_once(
    camera_feed: CarEndpointSpy,
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = local_streamer_settings(camera_feed, telemetry_feed, car_control)
    async with asyncio.timeout(WAIT_TIMEOUT_S), serve_streamer(settings) as streamer:
        wrong_path = urllib.parse.urljoin(streamer.drive, "/")
        with contextlib.suppress(DriveConnectionClosedError):
            await drive(HeldInputStub(), wrong_path)

    assert _connections_to(caplog.records, "/") == 1


def _connections_to(records: list[logging.LogRecord], path: str) -> int:
    return sum(
        record.name == "controller.streamer"
        and record.msg == "Server connection from: %s to %s"
        and isinstance(record.args, tuple)
        and record.args[1] == path
        for record in records
    )


def _connected_to(records: list[logging.LogRecord], uri: str) -> bool:
    return any(
        record.name == "controller.reconnecting_connection"
        and record.msg == "Connected to %s"
        and record.args == (uri,)
        for record in records
    )
