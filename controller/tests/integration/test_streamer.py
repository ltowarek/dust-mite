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

from controller.collision_monitor import CollisionMonitor
from controller.command import Command
from controller.streamer import CarFeeds, CommandMux, server_handler

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
    feeds = CarFeeds.connect(stream_uri=camera.uri, telemetry_uri=telemetry.uri)
    mux = CommandMux(control.uri, feeds.telemetry, CollisionMonitor())
    with _serve(functools.partial(server_handler, feeds, mux)) as server:
        yield server


def _uri(server: websockets.sync.server.Server, path: str = "/") -> str:
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


def test_dashboard_receives_camera_and_telemetry(
    camera_feed: FakeCarEndpoint,
    telemetry_feed: FakeCarEndpoint,
    car_control: FakeCarEndpoint,
) -> None:
    with (
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer)) as dashboard,
    ):
        _receive_types(dashboard, {"stream", "telemetry"})


def test_dashboards_share_one_car_connection_per_feed(
    camera_feed: FakeCarEndpoint,
    telemetry_feed: FakeCarEndpoint,
    car_control: FakeCarEndpoint,
) -> None:
    with (
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer)) as first,
        websockets.sync.client.connect(_uri(streamer)) as second,
    ):
        _receive_types(first, {"stream", "telemetry"})
        _receive_types(second, {"stream", "telemetry"})

    assert camera_feed.peak_connections == 1
    assert telemetry_feed.peak_connections == 1
    assert car_control.peak_connections == 0


def test_car_feeds_disconnect_after_the_last_dashboard_leaves(
    camera_feed: FakeCarEndpoint,
    telemetry_feed: FakeCarEndpoint,
    car_control: FakeCarEndpoint,
) -> None:
    with _streamer(camera_feed, telemetry_feed, car_control) as streamer:
        with websockets.sync.client.connect(_uri(streamer)) as dashboard:
            _receive_types(dashboard, {"stream", "telemetry"})

        assert _wait_for(lambda: camera_feed.open_connections == 0)
        assert _wait_for(lambda: telemetry_feed.open_connections == 0)


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


def test_drivers_share_one_control_connection(
    camera_feed: FakeCarEndpoint,
    telemetry_feed: FakeCarEndpoint,
    car_control: FakeCarEndpoint,
) -> None:
    with (
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(_uri(streamer, "/drive")) as first,
        websockets.sync.client.connect(_uri(streamer, "/drive")) as second,
    ):
        _send_command(first, Command.ADVANCE)
        _send_command(second, Command.RETREAT)
        assert _wait_for(lambda: len(car_control.received) == 2)  # noqa: PLR2004

    assert car_control.peak_connections == 1


def test_brakes_instead_of_advancing_into_an_obstacle(
    camera_feed: FakeCarEndpoint,
    car_control: FakeCarEndpoint,
) -> None:
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
