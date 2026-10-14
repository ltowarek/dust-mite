"""Test doubles for the car: real websocket endpoints standing in for its own.

Feed endpoints are stubs that send canned messages; every endpoint is a spy
that records its connections and the commands it receives.
"""

import base64
import contextlib
import dataclasses
import json
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import cv2
import numpy as np
import websockets.exceptions
import websockets.http11
import websockets.sync.server

__test__ = False

FEED_INTERVAL_S = 0.05
CLEAR_DISTANCE_CM = 100
OBSTACLE_DISTANCE_CM = 3

ProcessRequest = (
    Callable[
        [websockets.sync.server.ServerConnection, websockets.http11.Request],
        websockets.http11.Response | None,
    ]
    | None
)


@dataclasses.dataclass
class CarEndpointSpy:
    """A car endpoint that records its connections and the commands it receives."""

    server: websockets.sync.server.Server
    open_connections: int = 0
    peak_connections: int = 0
    received: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    @property
    def uri(self) -> str:
        host, port = self.server.socket.getsockname()[:2]
        return f"ws://{host}:{port}"


@contextlib.contextmanager
def serve(
    handler: Callable[[websockets.sync.server.ServerConnection], None],
    process_request: ProcessRequest = None,
) -> Iterator[websockets.sync.server.Server]:
    with websockets.sync.server.serve(
        handler, "localhost", 0, process_request=process_request
    ) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()


@contextlib.contextmanager
def car_endpoint_spy(
    serve_client: Callable[
        [websockets.sync.server.ServerConnection, CarEndpointSpy], None
    ],
    process_request: ProcessRequest = None,
) -> Iterator[CarEndpointSpy]:
    lock = threading.Lock()
    endpoint: CarEndpointSpy

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

    with serve(handler, process_request) as server:
        endpoint = CarEndpointSpy(server)
        yield endpoint


def car_feed_stub(
    message: Callable[[], dict[str, Any]],
    process_request: ProcessRequest = None,
) -> contextlib.AbstractContextManager[CarEndpointSpy]:
    def push_messages(
        websocket: websockets.sync.server.ServerConnection, _: CarEndpointSpy
    ) -> None:
        while True:
            websocket.send(json.dumps(message()))
            time.sleep(FEED_INTERVAL_S)

    return car_endpoint_spy(push_messages, process_request)


def car_control_spy() -> contextlib.AbstractContextManager[CarEndpointSpy]:
    def record_commands(
        websocket: websockets.sync.server.ServerConnection, endpoint: CarEndpointSpy
    ) -> None:
        for message in websocket:
            endpoint.received.append(json.loads(message))

    return car_endpoint_spy(record_commands)


def camera_frame() -> dict[str, Any]:
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    jpeg = cv2.imencode(".jpg", image)[1].tobytes()
    return {"data": base64.b64encode(jpeg).decode("ascii")}


def telemetry(distance_ahead: int) -> Callable[[], dict[str, Any]]:
    return lambda: {"distance_ahead": distance_ahead, "speed": 0.0}
