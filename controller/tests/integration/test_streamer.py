import base64
import contextlib
import dataclasses
import functools
import json
import threading
import time
from collections.abc import Callable, Generator, Iterator
from typing import Any

import cv2
import numpy as np
import pytest
import websockets.exceptions
import websockets.sync.client
import websockets.sync.connection
import websockets.sync.server
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics._internal.point import NumberDataPoint
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from websockets.frames import Close, CloseCode

from controller.collision_monitor import CollisionMonitor
from controller.command import Command
from controller.metrics import configure_metrics
from controller.senders import DriveConnectionClosedError, WebSocketCommandSender
from controller.streamer import (
    DRIVER_ALREADY_CONNECTED,
    CarFeed,
    CommandArbiter,
    camera_message,
    send_commands_to_car,
    server_handler,
    telemetry_message,
)
from controller.subject import Subject

_WAIT_TIMEOUT_S = 10
_FEED_INTERVAL_S = 0.05
_CLEAR_DISTANCE_CM = 100
_OBSTACLE_DISTANCE_CM = 3
_SPEED = 50


@dataclasses.dataclass
class FakeCarEndpoint:
    """A car endpoint that counts its connections."""

    server: websockets.sync.server.Server
    open_connections: int = 0
    peak_connections: int = 0
    received: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    @property
    def uri(self) -> str:
        host, port = self.server.socket.getsockname()[:2]
        return f"ws://{host}:{port}"


@contextlib.contextmanager
def _serve(
    handler: Callable[[websockets.sync.server.ServerConnection], None],
) -> Iterator[websockets.sync.server.Server]:
    with websockets.sync.server.serve(handler, "localhost", 0) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()


@contextlib.contextmanager
def _fake_car_endpoint(
    serve_client: Callable[
        [websockets.sync.server.ServerConnection, FakeCarEndpoint], None
    ],
) -> Iterator[FakeCarEndpoint]:
    lock = threading.Lock()
    endpoint: FakeCarEndpoint

    def handler(websocket: websockets.sync.server.ServerConnection) -> None:
        with lock:
            endpoint.open_connections += 1
            endpoint.peak_connections = max(
                endpoint.peak_connections, endpoint.open_connections
            )
        try:
            serve_client(websocket, endpoint)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            with lock:
                endpoint.open_connections -= 1

    with _serve(handler) as server:
        endpoint = FakeCarEndpoint(server)
        yield endpoint


def _fake_car_feed(
    message: Callable[[], dict[str, Any]],
) -> contextlib.AbstractContextManager[FakeCarEndpoint]:
    def push_messages(
        websocket: websockets.sync.server.ServerConnection, _: FakeCarEndpoint
    ) -> None:
        while True:
            websocket.send(json.dumps(message()))
            time.sleep(_FEED_INTERVAL_S)

    return _fake_car_endpoint(push_messages)


def _fake_car_control() -> contextlib.AbstractContextManager[FakeCarEndpoint]:
    def record_commands(
        websocket: websockets.sync.server.ServerConnection, endpoint: FakeCarEndpoint
    ) -> None:
        for message in websocket:
            endpoint.received.append(json.loads(message))

    return _fake_car_endpoint(record_commands)


def _camera_frame() -> dict[str, Any]:
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    jpeg = cv2.imencode(".jpg", image)[1].tobytes()
    return {"data": base64.b64encode(jpeg).decode("ascii")}


def _telemetry(distance_ahead: int) -> Callable[[], dict[str, Any]]:
    return lambda: {"distance_ahead": distance_ahead, "speed": 0.0}


@pytest.fixture
def camera_feed() -> Generator[FakeCarEndpoint, None, None]:
    with _fake_car_feed(_camera_frame) as feed:
        yield feed


@pytest.fixture
def telemetry_feed() -> Generator[FakeCarEndpoint, None, None]:
    with _fake_car_feed(_telemetry(_CLEAR_DISTANCE_CM)) as feed:
        yield feed


@pytest.fixture
def car_control() -> Generator[FakeCarEndpoint, None, None]:
    with _fake_car_control() as control:
        yield control


@contextlib.contextmanager
def _streamer(
    camera: FakeCarEndpoint, telemetry: FakeCarEndpoint, control: FakeCarEndpoint
) -> Iterator[websockets.sync.server.Server]:
    commands = Subject()
    car_camera = CarFeed(camera.uri, camera_message)
    car_telemetry = CarFeed(telemetry.uri, telemetry_message)
    arbiter = CommandArbiter(commands, car_telemetry, CollisionMonitor())
    with (
        send_commands_to_car(control.uri, commands),
        _serve(
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
    deadline = time.monotonic() + _WAIT_TIMEOUT_S
    while not wanted <= seen:
        remaining = deadline - time.monotonic()
        seen.add(json.loads(websocket.recv(timeout=remaining))["type"])


def _wait_for(condition: Callable[[], bool]) -> bool:
    deadline = time.monotonic() + _WAIT_TIMEOUT_S
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(_FEED_INTERVAL_S)
    return True


def _send_command(
    websocket: websockets.sync.connection.Connection, command: Command
) -> None:
    websocket.send(json.dumps({"command": command.value, "value": _SPEED}))


def test_camera_endpoint_streams_camera_frames(
    camera_feed: FakeCarEndpoint,
    telemetry_feed: FakeCarEndpoint,
    car_control: FakeCarEndpoint,
) -> None:
    with (
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/camera")) as client,
    ):
        _receive_types(client, {"stream"})

    assert telemetry_feed.peak_connections == 0


def test_telemetry_endpoint_streams_telemetry(
    camera_feed: FakeCarEndpoint,
    telemetry_feed: FakeCarEndpoint,
    car_control: FakeCarEndpoint,
) -> None:
    with (
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/telemetry")) as client,
    ):
        _receive_types(client, {"telemetry"})

    assert camera_feed.peak_connections == 0


def test_clients_share_one_car_connection_per_feed(
    camera_feed: FakeCarEndpoint,
    telemetry_feed: FakeCarEndpoint,
    car_control: FakeCarEndpoint,
) -> None:
    with (
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/camera")) as first,
        websockets.sync.client.connect(_uri(streamer, "/camera")) as second,
    ):
        _receive_types(first, {"stream"})
        _receive_types(second, {"stream"})

    assert camera_feed.peak_connections == 1


def test_car_feed_disconnects_after_the_last_client_leaves(
    camera_feed: FakeCarEndpoint,
    telemetry_feed: FakeCarEndpoint,
    car_control: FakeCarEndpoint,
) -> None:
    with _streamer(camera_feed, telemetry_feed, car_control) as streamer:
        with websockets.sync.client.connect(_uri(streamer, "/camera")) as client:
            _receive_types(client, {"stream"})

        assert _wait_for(lambda: camera_feed.open_connections == 0)


def test_closes_a_connection_to_an_unknown_path(
    camera_feed: FakeCarEndpoint,
    telemetry_feed: FakeCarEndpoint,
    car_control: FakeCarEndpoint,
) -> None:
    with (
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/")) as client,
        pytest.raises(websockets.exceptions.ConnectionClosedError),
    ):
        client.recv(timeout=_WAIT_TIMEOUT_S)


def test_opens_the_control_connection_before_any_driver_connects(
    camera_feed: FakeCarEndpoint,
    telemetry_feed: FakeCarEndpoint,
    car_control: FakeCarEndpoint,
) -> None:
    with _streamer(camera_feed, telemetry_feed, car_control):
        assert _wait_for(lambda: car_control.open_connections == 1)


def test_forwards_drive_commands_to_the_car(
    camera_feed: FakeCarEndpoint,
    telemetry_feed: FakeCarEndpoint,
    car_control: FakeCarEndpoint,
) -> None:
    with (
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/drive")) as driver,
    ):
        _send_command(driver, Command.ADVANCE)
        assert _wait_for(lambda: bool(car_control.received))

    assert car_control.received[0]["command"] == Command.ADVANCE.value
    assert car_control.received[0]["value"] == _SPEED


def test_refuses_a_second_driver(
    camera_feed: FakeCarEndpoint,
    telemetry_feed: FakeCarEndpoint,
    car_control: FakeCarEndpoint,
) -> None:
    with (
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/drive")) as first,
    ):
        _send_command(first, Command.ADVANCE)
        assert _wait_for(lambda: bool(car_control.received))

        with (
            websockets.sync.client.connect(_uri(streamer, "/drive")) as second,
            pytest.raises(websockets.exceptions.ConnectionClosedError) as closed,
        ):
            second.recv(timeout=_WAIT_TIMEOUT_S)

    assert closed.value.rcvd == Close(
        CloseCode.TRY_AGAIN_LATER, DRIVER_ALREADY_CONNECTED
    )


def test_accepts_a_new_driver_after_the_previous_one_leaves(
    camera_feed: FakeCarEndpoint,
    telemetry_feed: FakeCarEndpoint,
    car_control: FakeCarEndpoint,
) -> None:
    def turn_left_as_a_new_driver() -> bool:
        try:
            with websockets.sync.client.connect(_uri(streamer, "/drive")) as driver:
                _send_command(driver, Command.TURN_LEFT)
        except websockets.exceptions.ConnectionClosed:
            return False
        return any(
            command["command"] == Command.TURN_LEFT.value
            for command in car_control.received
        )

    with _streamer(camera_feed, telemetry_feed, car_control) as streamer:
        with websockets.sync.client.connect(_uri(streamer, "/drive")) as first:
            _send_command(first, Command.ADVANCE)

        assert _wait_for(turn_left_as_a_new_driver)


def _blocked_commands(reader: InMemoryMetricReader) -> dict[str, int]:
    data = reader.get_metrics_data()
    blocked: dict[str, int] = {}
    if data is None:
        return blocked
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name != "dust_mite_commands_blocked":
                    continue
                for point in metric.data.data_points:
                    if isinstance(point, NumberDataPoint) and point.attributes:
                        name = str(point.attributes["command.name"])
                        blocked[name] = blocked.get(name, 0) + int(point.value)
    return blocked


def test_brakes_instead_of_advancing_into_an_obstacle(
    camera_feed: FakeCarEndpoint,
    car_control: FakeCarEndpoint,
) -> None:
    reader = InMemoryMetricReader()
    configure_metrics("test-streamer", MeterProvider(metric_readers=[reader]))

    def received_brake() -> bool:
        return any(c["command"] == Command.BRAKE.value for c in car_control.received)

    with (
        _fake_car_feed(_telemetry(_OBSTACLE_DISTANCE_CM)) as telemetry_feed,
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/drive")) as driver,
    ):

        def advance_until_braked() -> bool:
            _send_command(driver, Command.ADVANCE)
            return received_brake()

        assert _wait_for(advance_until_braked)

    assert set(_blocked_commands(reader)) == {Command.ADVANCE.name}


def _receive_collision_state(
    websocket: websockets.sync.connection.Connection,
) -> bool:
    deadline = time.monotonic() + _WAIT_TIMEOUT_S
    while True:
        message = json.loads(websocket.recv(timeout=deadline - time.monotonic()))
        if message["type"] == "collision_monitor":
            return bool(message["stopping"])


def test_publishes_collision_monitor_state_on_the_telemetry_endpoint(
    camera_feed: FakeCarEndpoint,
    car_control: FakeCarEndpoint,
) -> None:
    with (
        _fake_car_feed(_telemetry(_OBSTACLE_DISTANCE_CM)) as telemetry_feed,
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/telemetry")) as client,
    ):
        # Only changes are published, so subscribe before a driver attaches.
        _receive_types(client, {"telemetry"})
        with websockets.sync.client.connect(_uri(streamer, "/drive")):
            assert _receive_collision_state(client) is True


def test_the_controller_cli_drives_through_the_streamer(
    camera_feed: FakeCarEndpoint,
    telemetry_feed: FakeCarEndpoint,
    car_control: FakeCarEndpoint,
) -> None:
    with (
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        WebSocketCommandSender(_uri(streamer, "/drive")) as sender,
    ):
        sender.send(Command.TURN_LEFT, _SPEED)
        assert _wait_for(lambda: bool(car_control.received))

    assert car_control.received[0]["command"] == Command.TURN_LEFT.value


def _keep_sending(sender: WebSocketCommandSender) -> None:
    deadline = time.monotonic() + _WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        sender.send(Command.BRAKE, None)
        time.sleep(_FEED_INTERVAL_S)


def test_tells_a_refused_cli_why(
    camera_feed: FakeCarEndpoint,
    telemetry_feed: FakeCarEndpoint,
    car_control: FakeCarEndpoint,
) -> None:
    with (
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/drive")) as first,
    ):
        _send_command(first, Command.ADVANCE)
        assert _wait_for(lambda: bool(car_control.received))

        with (
            WebSocketCommandSender(_uri(streamer, "/drive")) as second,
            pytest.raises(DriveConnectionClosedError, match=DRIVER_ALREADY_CONNECTED),
        ):
            _keep_sending(second)
