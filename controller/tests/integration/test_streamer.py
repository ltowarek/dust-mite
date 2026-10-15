"""Streamer integration tests.

Real clients talk to the streamer, which talks to car test doubles.
"""

import contextlib
import functools
import json
import time
from collections.abc import Iterator

import pytest
import websockets.exceptions
import websockets.sync.client
import websockets.sync.connection
import websockets.sync.server
from websockets.frames import Close, CloseCode

from controller.car import CarFeed, Message, send_commands_to_car
from controller.collision_monitor import CollisionMonitor
from controller.command import Command
from controller.command_arbiter import DRIVER_ALREADY_CONNECTED, CommandArbiter
from controller.senders import WebSocketCommandSender
from controller.streamer import camera_message, server_handler, telemetry_message
from controller.subject import Subject

from .test_doubles import (
    OBSTACLE_DISTANCE_CM,
    CarEndpointSpy,
    car_feed_stub,
    serve,
    telemetry,
)
from .waiting import WAIT_TIMEOUT_S, wait_for

_SPEED = 50


@contextlib.contextmanager
def _streamer(
    camera: CarEndpointSpy, telemetry: CarEndpointSpy, control: CarEndpointSpy
) -> Iterator[websockets.sync.server.Server]:
    commands = Subject[Message]()
    car_camera = CarFeed(camera.uri, camera_message)
    car_telemetry = CarFeed(telemetry.uri, telemetry_message)
    arbiter = CommandArbiter(commands, car_telemetry, CollisionMonitor())
    with (
        send_commands_to_car(control.uri, commands),
        serve(
            functools.partial(server_handler, car_camera, car_telemetry, arbiter)
        ) as server,
    ):
        yield server


def _uri(server: websockets.sync.server.Server, path: str) -> str:
    host, port = server.socket.getsockname()[:2]
    return f"ws://{host}:{port}{path}"


def _receive_types(
    websocket: websockets.sync.connection.Connection, wanted: set[str]
) -> None:
    seen: set[str] = set()
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    while not wanted <= seen:
        remaining = deadline - time.monotonic()
        seen.add(json.loads(websocket.recv(timeout=remaining))["type"])


def _send_command(
    websocket: websockets.sync.connection.Connection, command: Command
) -> None:
    websocket.send(json.dumps({"command": command.value, "value": _SPEED}))


def test_camera_endpoint_streams_camera_frames(
    camera_feed: CarEndpointSpy,
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
) -> None:
    with (
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/camera")) as client,
    ):
        _receive_types(client, {"stream"})

    assert telemetry_feed.peak_connections == 0


def test_telemetry_endpoint_streams_telemetry(
    camera_feed: CarEndpointSpy,
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
) -> None:
    with (
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/telemetry")) as client,
    ):
        _receive_types(client, {"telemetry"})

    assert camera_feed.peak_connections == 0


def test_closes_a_connection_to_an_unknown_path(
    camera_feed: CarEndpointSpy,
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
) -> None:
    with (
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/")) as client,
        pytest.raises(websockets.exceptions.ConnectionClosedError),
    ):
        client.recv(timeout=WAIT_TIMEOUT_S)


def test_forwards_drive_commands_to_the_car(
    camera_feed: CarEndpointSpy,
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
) -> None:
    with (
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/drive")) as driver,
    ):
        _send_command(driver, Command.ADVANCE)
        assert wait_for(lambda: bool(car_control.received))

    assert (
        car_control.received[0].items()
        >= {
            "command": Command.ADVANCE.value,
            "value": _SPEED,
        }.items()
    )


def test_refuses_a_second_driver(
    camera_feed: CarEndpointSpy,
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
) -> None:
    with (
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/drive")) as first,
    ):
        _send_command(first, Command.ADVANCE)
        assert wait_for(lambda: bool(car_control.received))

        with (
            websockets.sync.client.connect(_uri(streamer, "/drive")) as second,
            pytest.raises(websockets.exceptions.ConnectionClosedError) as closed,
        ):
            second.recv(timeout=WAIT_TIMEOUT_S)

    assert closed.value.rcvd == Close(
        CloseCode.TRY_AGAIN_LATER, DRIVER_ALREADY_CONNECTED
    )


def _receive_collision_state(
    websocket: websockets.sync.connection.Connection,
) -> bool:
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    while True:
        message = json.loads(websocket.recv(timeout=deadline - time.monotonic()))
        if message["type"] == "collision_monitor":
            return bool(message["stopping"])


def test_publishes_collision_monitor_state_on_the_telemetry_endpoint(
    camera_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
) -> None:
    with (
        car_feed_stub(telemetry(OBSTACLE_DISTANCE_CM)) as telemetry_feed,
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/telemetry")) as client,
    ):
        # Only changes are published, so subscribe before a driver attaches.
        _receive_types(client, {"telemetry"})
        with websockets.sync.client.connect(_uri(streamer, "/drive")):
            assert _receive_collision_state(client) is True


def test_the_controller_cli_drives_through_the_streamer(
    camera_feed: CarEndpointSpy,
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
) -> None:
    with (
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        WebSocketCommandSender(_uri(streamer, "/drive")) as sender,
    ):
        sender.send(Command.TURN_LEFT, _SPEED)
        assert wait_for(lambda: bool(car_control.received))

    assert car_control.received[0]["command"] == Command.TURN_LEFT.value
