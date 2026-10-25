"""Streamer integration tests.

Real clients talk to the streamer, which talks to car test doubles.
"""

import contextlib
import functools
import http
import http.client
import json
import threading
import time
from collections.abc import Iterator

import pytest
import websockets.exceptions
import websockets.sync.client
import websockets.sync.connection
import websockets.sync.server
from websockets.frames import Close, CloseCode

from controller.car import CarFeed, send_commands_to_car
from controller.collision_monitor import CollisionMonitor
from controller.command import Command
from controller.command_arbiter import DRIVER_ALREADY_CONNECTED, CommandArbiter
from controller.mjpeg import CameraStreamPart, MjpegClient, read_part
from controller.senders import WebSocketCommandSender
from controller.streamer import (
    CAMERA_PATH,
    CameraServer,
    relay_camera_part,
    relay_telemetry_message,
    server_handler,
)
from controller.subject import Subject
from controller.websocket_client import WebSocketClient
from controller.websocket_message import WebSocketMessage

from .test_doubles import (
    CAR_TRACEPARENT,
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
    telemetry: CarEndpointSpy, control: CarEndpointSpy
) -> Iterator[websockets.sync.server.Server]:
    commands = Subject[WebSocketMessage]()
    car_telemetry = CarFeed(
        functools.partial(WebSocketClient, telemetry.uri, "r"),
        relay_telemetry_message,
    )
    arbiter = CommandArbiter(commands, car_telemetry, CollisionMonitor())
    with (
        send_commands_to_car(control.uri, commands),
        serve(functools.partial(server_handler, car_telemetry, arbiter)) as server,
    ):
        yield server


@contextlib.contextmanager
def _camera_server(camera: CarEndpointSpy) -> Iterator[CameraServer]:
    car_camera = CarFeed(functools.partial(MjpegClient, camera.uri), relay_camera_part)
    with CameraServer(("localhost", 0), car_camera) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()


@contextlib.contextmanager
def _viewer(
    server: CameraServer, path: str = CAMERA_PATH
) -> Iterator[http.client.HTTPResponse]:
    host, port = server.server_address[:2]
    connection = http.client.HTTPConnection(str(host), port, timeout=WAIT_TIMEOUT_S)
    try:
        connection.request("GET", path)
        with connection.getresponse() as response:
            yield response
    finally:
        connection.close()


def _first_part(camera: CarEndpointSpy) -> CameraStreamPart:
    with _camera_server(camera) as server, _viewer(server) as stream:
        return read_part(stream)


def _uri(server: websockets.sync.server.Server, path: str) -> str:
    host, port = server.socket.getsockname()[:2]
    return f"ws://{host}:{port}{path}"


def _receive_types(
    websocket: websockets.sync.connection.Connection, wanted: set[str]
) -> set[str]:
    seen: set[str] = set()
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    while not wanted <= seen:
        remaining = deadline - time.monotonic()
        seen.add(json.loads(websocket.recv(timeout=remaining))["type"])
    return seen


def _send_command(
    websocket: websockets.sync.connection.Connection, command: Command
) -> None:
    websocket.send(json.dumps({"command": command.value, "value": _SPEED}))


def test_camera_server_streams_jpeg_parts(camera_feed: CarEndpointSpy) -> None:
    assert _first_part(camera_feed).jpeg[:2] == b"\xff\xd8"


def test_camera_server_parts_continue_the_car_trace(
    camera_feed: CarEndpointSpy,
) -> None:
    traceparent = _first_part(camera_feed).headers["traceparent"]

    assert traceparent.split("-")[1] == CAR_TRACEPARENT.split("-")[1]


def test_camera_server_refuses_an_unknown_path(camera_feed: CarEndpointSpy) -> None:
    with _camera_server(camera_feed) as server, _viewer(server, "/") as response:
        assert response.status == http.HTTPStatus.NOT_FOUND


def test_camera_server_releases_the_car_after_the_last_viewer_leaves(
    camera_feed: CarEndpointSpy,
) -> None:
    with _camera_server(camera_feed) as server:
        with _viewer(server) as stream:
            read_part(stream)

        assert wait_for(lambda: camera_feed.open_connections == 0)


def test_telemetry_endpoint_streams_telemetry(
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
) -> None:
    with (
        _streamer(telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/telemetry")) as client,
    ):
        assert "telemetry" in _receive_types(client, {"telemetry"})


def test_closes_a_connection_to_an_unknown_path(
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
) -> None:
    with (
        _streamer(telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/")) as client,
        pytest.raises(websockets.exceptions.ConnectionClosedError),
    ):
        client.recv(timeout=WAIT_TIMEOUT_S)


def test_forwards_drive_commands_to_the_car(
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
) -> None:
    with (
        _streamer(telemetry_feed, car_control) as streamer,
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
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
) -> None:
    with (
        _streamer(telemetry_feed, car_control) as streamer,
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
    car_control: CarEndpointSpy,
) -> None:
    with (
        car_feed_stub(telemetry(OBSTACLE_DISTANCE_CM)) as telemetry_feed,
        _streamer(telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/telemetry")) as client,
    ):
        # Only changes are published, so subscribe before a driver attaches.
        _receive_types(client, {"telemetry"})
        with websockets.sync.client.connect(_uri(streamer, "/drive")):
            assert _receive_collision_state(client) is True


def test_the_controller_cli_drives_through_the_streamer(
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
) -> None:
    with (
        _streamer(telemetry_feed, car_control) as streamer,
        WebSocketCommandSender(_uri(streamer, "/drive")) as sender,
    ):
        sender.send(Command.TURN_LEFT, _SPEED)
        assert wait_for(lambda: bool(car_control.received))

    assert car_control.received[0]["command"] == Command.TURN_LEFT.value
