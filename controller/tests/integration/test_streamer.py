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

from controller.command import Command
from controller.streamer import CarFeeds, server_handler

from .conftest import LocalServer

_WAIT_TIMEOUT_S = 10
_FEED_INTERVAL_S = 0.05
_CLEAR_DISTANCE_CM = 100
_OBSTACLE_DISTANCE_CM = 3


@dataclasses.dataclass
class FakeCarFeed:
    """A car endpoint that keeps pushing messages to every connected client."""

    server: websockets.sync.server.Server
    open_connections: int = 0
    peak_connections: int = 0

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
def _fake_car_feed(message: Callable[[], dict[str, Any]]) -> Iterator[FakeCarFeed]:
    lock = threading.Lock()
    feed: FakeCarFeed

    def handler(websocket: websockets.sync.server.ServerConnection) -> None:
        with lock:
            feed.open_connections += 1
            feed.peak_connections = max(feed.peak_connections, feed.open_connections)
        try:
            while True:
                websocket.send(json.dumps(message()))
                time.sleep(_FEED_INTERVAL_S)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            with lock:
                feed.open_connections -= 1

    with _serve(handler) as server:
        feed = FakeCarFeed(server)
        yield feed


def _camera_frame() -> dict[str, Any]:
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    jpeg = cv2.imencode(".jpg", image)[1].tobytes()
    return {"data": base64.b64encode(jpeg).decode("ascii")}


def _telemetry(distance_ahead: int) -> Callable[[], dict[str, Any]]:
    return lambda: {"distance_ahead": distance_ahead, "speed": 0.0}


@pytest.fixture
def camera_feed() -> Generator[FakeCarFeed, None, None]:
    with _fake_car_feed(_camera_frame) as feed:
        yield feed


@pytest.fixture
def telemetry_feed() -> Generator[FakeCarFeed, None, None]:
    with _fake_car_feed(_telemetry(_CLEAR_DISTANCE_CM)) as feed:
        yield feed


@contextlib.contextmanager
def _streamer(
    camera_uri: str, telemetry_uri: str
) -> Iterator[websockets.sync.server.Server]:
    feeds = CarFeeds.connect(stream_uri=camera_uri, telemetry_uri=telemetry_uri)
    with _serve(functools.partial(server_handler, feeds)) as server:
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


def test_dashboard_receives_camera_and_telemetry(
    camera_feed: FakeCarFeed,
    telemetry_feed: FakeCarFeed,
    local_server: LocalServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTROLLER_CLIENT_URI", local_server.uri)

    with (
        _streamer(camera_feed.uri, telemetry_feed.uri) as streamer,
        websockets.sync.client.connect(_uri(streamer)) as dashboard,
    ):
        _receive_types(dashboard, {"stream", "telemetry"})


def test_dashboards_share_one_car_connection_per_feed(
    camera_feed: FakeCarFeed,
    telemetry_feed: FakeCarFeed,
    local_server: LocalServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTROLLER_CLIENT_URI", local_server.uri)

    with (
        _streamer(camera_feed.uri, telemetry_feed.uri) as streamer,
        websockets.sync.client.connect(_uri(streamer)) as first,
        websockets.sync.client.connect(_uri(streamer)) as second,
    ):
        _receive_types(first, {"stream", "telemetry"})
        _receive_types(second, {"stream", "telemetry"})

    assert camera_feed.peak_connections == 1
    assert telemetry_feed.peak_connections == 1


def test_car_feeds_disconnect_after_the_last_dashboard_leaves(
    camera_feed: FakeCarFeed,
    telemetry_feed: FakeCarFeed,
    local_server: LocalServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTROLLER_CLIENT_URI", local_server.uri)

    with _streamer(camera_feed.uri, telemetry_feed.uri) as streamer:
        with websockets.sync.client.connect(_uri(streamer)) as dashboard:
            _receive_types(dashboard, {"stream", "telemetry"})

        assert _wait_for(lambda: camera_feed.open_connections == 0)
        assert _wait_for(lambda: telemetry_feed.open_connections == 0)


def test_brakes_when_an_obstacle_is_ahead(
    camera_feed: FakeCarFeed,
    local_server: LocalServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTROLLER_CLIENT_URI", local_server.uri)

    with (
        _fake_car_feed(_telemetry(_OBSTACLE_DISTANCE_CM)) as telemetry_feed,
        _streamer(camera_feed.uri, telemetry_feed.uri) as streamer,
        websockets.sync.client.connect(_uri(streamer)),
    ):
        assert local_server.message_received.wait(timeout=_WAIT_TIMEOUT_S)

    assert local_server.received[0]["command"] == Command.BRAKE.value
