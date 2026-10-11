import dataclasses
import json
import threading
from collections.abc import Generator, Iterator
from typing import Any

import pytest
import websockets.sync.server

from .car_doubles import (
    CLEAR_DISTANCE_CM,
    CarEndpointSpy,
    camera_frame,
    car_control_spy,
    car_feed_stub,
    telemetry,
)


@dataclasses.dataclass
class LocalServer:
    server: websockets.sync.server.Server
    received: list[dict[str, Any]]
    message_received: threading.Event

    @property
    def uri(self) -> str:
        host, port = self.server.socket.getsockname()[:2]
        return f"ws://{host}:{port}"


@pytest.fixture
def local_server() -> Generator[LocalServer, None, None]:
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
            yield LocalServer(server, received, message_received)
        finally:
            server.shutdown()
            thread.join()


@pytest.fixture
def camera_feed() -> Iterator[CarEndpointSpy]:
    with car_feed_stub(camera_frame) as feed:
        yield feed


@pytest.fixture
def telemetry_feed() -> Iterator[CarEndpointSpy]:
    with car_feed_stub(telemetry(CLEAR_DISTANCE_CM)) as feed:
        yield feed


@pytest.fixture
def car_control() -> Iterator[CarEndpointSpy]:
    with car_control_spy() as control:
        yield control
