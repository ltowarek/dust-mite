"""Guards the controller CLI's drive loop against the in-process streamer."""

import asyncio
import contextlib
import logging
import socket
import threading
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
    """Input backend returning the Drive command the test holds, until told to quit."""

    def __init__(self) -> None:
        self._held: DriveCommand = (Command.BRAKE, None)
        self._quit = threading.Event()

    def hold(self, command: Command, value: int | None) -> None:
        self._held = (command, value)

    def quit(self) -> None:
        self._quit.set()

    def poll(self) -> DriveCommand | None:
        poll_interval_s = 0.05
        if self._quit.wait(poll_interval_s):
            return None
        return self._held


async def _eventually(condition: Callable[[], bool]) -> bool:
    return await asyncio.to_thread(wait_for, condition)


def _received_values(control: CarEndpointSpy) -> list[int]:
    return [command["value"] for command in control.received]


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
