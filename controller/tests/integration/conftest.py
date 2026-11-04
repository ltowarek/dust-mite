import dataclasses
import json
import os
import threading
from collections.abc import Generator, Iterator
from typing import Any

import pytest
import websockets.sync.server

from controller.streamer import StreamerSettings

from .test_doubles import (
    CLEAR_DISTANCE_CM,
    CarEndpointSpy,
    car_camera_stub,
    car_control_spy,
    car_feed_stub,
    telemetry,
)


@dataclasses.dataclass
class LocalServerSpy:
    server: websockets.sync.server.Server
    received: list[dict[str, Any]]
    message_received: threading.Event

    @property
    def uri(self) -> str:
        host, port = self.server.socket.getsockname()[:2]
        return f"ws://{host}:{port}"


@pytest.fixture
def local_server_spy() -> Generator[LocalServerSpy, None, None]:
    received: list[dict[str, Any]] = []
    message_received = threading.Event()

    def handler(websocket: websockets.sync.server.ServerConnection) -> None:
        # Keep receiving for the connection's full lifetime: returning after
        # one message closes it (`websockets` ties handler lifetime to
        # connection lifetime), which breaks callers that send more than one
        # message over the same connection.
        for message in websocket:
            received.append(json.loads(message))
            message_received.set()

    with websockets.sync.server.serve(handler, "localhost", 0) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield LocalServerSpy(server, received, message_received)
        finally:
            server.shutdown()
            thread.join()


@pytest.fixture
def camera_feed() -> Iterator[CarEndpointSpy]:
    with car_camera_stub() as feed:
        yield feed


@pytest.fixture
def telemetry_feed() -> Iterator[CarEndpointSpy]:
    with car_feed_stub(telemetry(CLEAR_DISTANCE_CM)) as feed:
        yield feed


@pytest.fixture
def car_control() -> Iterator[CarEndpointSpy]:
    with car_control_spy() as control:
        yield control


def local_streamer_settings(
    camera: CarEndpointSpy,
    telemetry: CarEndpointSpy,
    control: CarEndpointSpy,
    websocket_port: int = 0,
) -> StreamerSettings:
    """Settings for a streamer on loopback in front of the given car doubles."""
    return dataclasses.replace(
        StreamerSettings.from_env(
            {
                "STREAM_CLIENT_URI": camera.uri,
                "TELEMETRY_CLIENT_URI": telemetry.uri,
                "DRIVE_CLIENT_URI": control.uri,
                "STREAMER_CAMERA_PORT": "0",
            }
        ),
        listen_host="127.0.0.1",
        websocket_port=websocket_port,
    )


@pytest.fixture
def streamer_settings() -> StreamerSettings:
    """The streamer's own settings, for tests that reach the car it is set up for."""
    return StreamerSettings.from_env(os.environ)
