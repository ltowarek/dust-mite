"""Guards the streamer as real clients see it through its Streamer endpoints."""

import contextlib
import dataclasses
import http
import http.client
import json
import socket
import time
import urllib.parse
from collections.abc import Callable, Iterator

import pytest
import websockets.exceptions
import websockets.sync.client
import websockets.sync.connection
from websockets.frames import Close

from controller.command import Command
from controller.senders import WebSocketCommandSender
from controller.streamer import StreamerEndpoints, StreamerSettings, serve_streamer

from .test_doubles import (
    CAR_TRACEPARENT,
    CLEAR_DISTANCE_CM,
    OBSTACLE_DISTANCE_CM,
    CarEndpointSpy,
    MjpegPart,
    busy_refusals,
    car_camera_stub,
    car_feed_stub,
    read_mjpeg_part,
    telemetry,
)
from .waiting import WAIT_TIMEOUT_S, wait_for

_SPEED = 50
# Drive commands on the wire, as the web page sends them.
_ADVANCE = 1
_TURN_LEFT = 4
_TRY_AGAIN_LATER = 1013
_DRIVER_ALREADY_CONNECTED = "another driver is connected"
_CLIENTS_THAT_COME_AND_GO = 3
# Every hop waits 1 s before reconnecting to the car.
_LONGER_THAN_A_RECONNECT_S = 2.0
# Large enough that a Viewer that stops reading fills its socket buffers.
_LARGE_FRAME_PADDING = bytes(1_000_000)
_SMALL_RECEIVE_BUFFER = 4096
_WARM_UP_PARTS = 10
_READING_WINDOW_S = 2.0
_MIN_PARTS_IN_WINDOW = 10


@contextlib.contextmanager
def _streamer(
    camera: CarEndpointSpy,
    telemetry: CarEndpointSpy,
    control: CarEndpointSpy,
    process_camera_frame: Callable[[bytes], bytes] | None = None,
) -> Iterator[StreamerEndpoints]:
    settings = dataclasses.replace(
        StreamerSettings.from_env(
            {
                "STREAM_CLIENT_URI": camera.uri,
                "TELEMETRY_CLIENT_URI": telemetry.uri,
                "DRIVE_CLIENT_URI": control.uri,
                "STREAMER_CAMERA_PORT": "0",
            }
        ),
        listen_host="127.0.0.1",
        websocket_port=0,
    )
    processor = (
        {} if process_camera_frame is None else {"process": process_camera_frame}
    )
    with serve_streamer(settings, **processor) as endpoints:
        yield endpoints


@pytest.fixture
def streamer(
    camera_feed: CarEndpointSpy,
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
) -> Iterator[StreamerEndpoints]:
    with _streamer(camera_feed, telemetry_feed, car_control) as endpoints:
        yield endpoints


@dataclasses.dataclass(frozen=True)
class _Viewer:
    connection: http.client.HTTPConnection
    response: http.client.HTTPResponse


@contextlib.contextmanager
def _viewer(url: str) -> Iterator[_Viewer]:
    parts = urllib.parse.urlsplit(url)
    connection = http.client.HTTPConnection(
        parts.hostname or "", parts.port, timeout=WAIT_TIMEOUT_S
    )
    try:
        connection.request("GET", parts.path)
        with connection.getresponse() as response:
            yield _Viewer(connection, response)
    finally:
        connection.close()


@contextlib.contextmanager
def _viewer_that_stops_reading(url: str) -> Iterator[None]:
    parts = urllib.parse.urlsplit(url)
    with socket.socket() as viewer:
        # Set before connecting, so the advertised window stays small.
        viewer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, _SMALL_RECEIVE_BUFFER)
        viewer.connect((parts.hostname or "", parts.port or 0))
        viewer.sendall(
            f"GET {parts.path} HTTP/1.1\r\nHost: {parts.netloc}\r\n\r\n".encode()
        )
        yield


def _first_part(url: str) -> MjpegPart:
    with _viewer(url) as viewer:
        return read_mjpeg_part(viewer.response)


def _parts_within(viewer: _Viewer, seconds: float) -> int:
    count = 0
    deadline = time.monotonic() + seconds
    with contextlib.suppress(TimeoutError):
        while (remaining := deadline - time.monotonic()) > 0:
            if viewer.connection.sock is not None:
                viewer.connection.sock.settimeout(remaining)
            read_mjpeg_part(viewer.response)
            count += 1
    return count


def _receive_types(
    websocket: websockets.sync.connection.Connection, wanted: set[str]
) -> set[str]:
    seen: set[str] = set()
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    while not wanted <= seen:
        remaining = deadline - time.monotonic()
        seen.add(json.loads(websocket.recv(timeout=remaining))["type"])
    return seen


def _receive_collision_state(
    websocket: websockets.sync.connection.Connection,
) -> bool:
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    while True:
        message = json.loads(websocket.recv(timeout=deadline - time.monotonic()))
        if message["type"] == "collision_monitor":
            return bool(message["stopping"])


def _send_command(
    websocket: websockets.sync.connection.Connection, command: int
) -> None:
    websocket.send(json.dumps({"command": command, "value": _SPEED}))


@pytest.mark.parametrize(
    ("endpoint", "path"),
    [
        pytest.param("drive", "/drive", id="drive"),
        pytest.param("telemetry", "/telemetry", id="telemetry"),
        pytest.param("camera", "/camera", id="camera"),
    ],
)
def test_serves_each_streamer_endpoint_on_its_path(
    streamer: StreamerEndpoints, endpoint: str, path: str
) -> None:
    assert urllib.parse.urlsplit(getattr(streamer, endpoint)).path == path


@pytest.mark.usefixtures("streamer")
def test_opens_the_cars_drive_endpoint_at_once(car_control: CarEndpointSpy) -> None:
    assert wait_for(lambda: car_control.open_connections == 1)


def test_forwards_drive_commands_to_the_car(
    streamer: StreamerEndpoints, car_control: CarEndpointSpy
) -> None:
    with websockets.sync.client.connect(streamer.drive) as driver:
        _send_command(driver, _ADVANCE)
        wait_for(lambda: bool(car_control.received))

    assert (
        car_control.received[0].items()
        >= {"command": _ADVANCE, "value": _SPEED}.items()
    )


def test_refuses_a_second_driver(
    streamer: StreamerEndpoints, car_control: CarEndpointSpy
) -> None:
    with websockets.sync.client.connect(streamer.drive) as first:
        _send_command(first, _ADVANCE)
        wait_for(lambda: bool(car_control.received))

        with (
            websockets.sync.client.connect(streamer.drive) as second,
            pytest.raises(websockets.exceptions.ConnectionClosedError) as closed,
        ):
            second.recv(timeout=WAIT_TIMEOUT_S)

    assert closed.value.rcvd == Close(_TRY_AGAIN_LATER, _DRIVER_ALREADY_CONNECTED)


def test_closes_a_connection_to_an_unknown_path(streamer: StreamerEndpoints) -> None:
    unknown = urllib.parse.urljoin(streamer.drive, "/")
    with (
        websockets.sync.client.connect(unknown) as client,
        pytest.raises(websockets.exceptions.ConnectionClosedError),
    ):
        client.recv(timeout=WAIT_TIMEOUT_S)


def test_the_controller_cli_drives_through_the_streamer(
    streamer: StreamerEndpoints, car_control: CarEndpointSpy
) -> None:
    with WebSocketCommandSender(streamer.drive) as sender:
        sender.send(Command.TURN_LEFT, _SPEED)
        wait_for(lambda: bool(car_control.received))

    assert car_control.received[0]["command"] == _TURN_LEFT


def test_streams_telemetry(streamer: StreamerEndpoints) -> None:
    with websockets.sync.client.connect(streamer.telemetry) as client:
        assert "telemetry" in _receive_types(client, {"telemetry"})


def test_publishes_collision_monitor_state_on_the_telemetry_endpoint(
    camera_feed: CarEndpointSpy, car_control: CarEndpointSpy
) -> None:
    with (
        car_feed_stub(telemetry(OBSTACLE_DISTANCE_CM)) as telemetry_feed,
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(streamer.telemetry) as client,
    ):
        # Only changes are published, so subscribe before a driver attaches.
        _receive_types(client, {"telemetry"})
        with websockets.sync.client.connect(streamer.drive):
            assert _receive_collision_state(client) is True


def test_keeps_retrying_while_the_cars_telemetry_endpoint_is_busy(
    camera_feed: CarEndpointSpy, car_control: CarEndpointSpy
) -> None:
    with (
        car_feed_stub(
            telemetry(CLEAR_DISTANCE_CM), process_request=busy_refusals(1)
        ) as telemetry_feed,
        _streamer(camera_feed, telemetry_feed, car_control) as streamer,
        websockets.sync.client.connect(streamer.telemetry) as client,
    ):
        assert "telemetry" in _receive_types(client, {"telemetry"})


def test_camera_stream_parts_carry_a_jpeg(streamer: StreamerEndpoints) -> None:
    assert _first_part(streamer.camera).jpeg[:2] == b"\xff\xd8"


def test_camera_stream_parts_continue_the_car_trace(
    streamer: StreamerEndpoints,
) -> None:
    traceparent = _first_part(streamer.camera).headers["traceparent"]

    assert traceparent.split("-")[1] == CAR_TRACEPARENT.split("-")[1]


def test_refuses_an_unknown_camera_path(streamer: StreamerEndpoints) -> None:
    with _viewer(urllib.parse.urljoin(streamer.camera, "/")) as viewer:
        assert viewer.response.status == http.HTTPStatus.NOT_FOUND


def test_keeps_retrying_while_the_cars_camera_endpoint_is_busy(
    telemetry_feed: CarEndpointSpy, car_control: CarEndpointSpy
) -> None:
    with (
        car_camera_stub(refusals=1) as camera,
        _streamer(camera, telemetry_feed, car_control) as streamer,
    ):
        assert _first_part(streamer.camera).jpeg[:2] == b"\xff\xd8"


def test_releases_the_cars_camera_endpoint_after_the_last_viewer_leaves(
    streamer: StreamerEndpoints, camera_feed: CarEndpointSpy
) -> None:
    _first_part(streamer.camera)

    assert wait_for(lambda: camera_feed.open_connections == 0)


def test_the_last_viewer_leaving_a_stalled_camera_stream_releases_the_car(
    telemetry_feed: CarEndpointSpy, car_control: CarEndpointSpy
) -> None:
    with (
        car_camera_stub(stalled=True) as camera,
        _streamer(camera, telemetry_feed, car_control) as streamer,
    ):
        with _viewer(streamer.camera):
            wait_for(lambda: camera.open_connections == 1)
        wait_for(lambda: camera.open_connections == 0)
        time.sleep(_LONGER_THAN_A_RECONNECT_S)

        assert camera.open_connections == 0


def test_viewers_that_come_and_go_share_one_car_connection(
    streamer: StreamerEndpoints, camera_feed: CarEndpointSpy
) -> None:
    with _viewer(streamer.camera) as long_lived_viewer:
        read_mjpeg_part(long_lived_viewer.response)
        for _ in range(_CLIENTS_THAT_COME_AND_GO):
            _first_part(streamer.camera)

    assert camera_feed.peak_connections == 1


def test_telemetry_clients_and_drivers_that_come_and_go_share_one_car_connection(
    streamer: StreamerEndpoints, telemetry_feed: CarEndpointSpy
) -> None:
    with websockets.sync.client.connect(streamer.telemetry) as long_lived_client:
        _receive_types(long_lived_client, {"telemetry"})
        for _ in range(_CLIENTS_THAT_COME_AND_GO):
            with websockets.sync.client.connect(streamer.telemetry) as client:
                _receive_types(client, {"telemetry"})
            with websockets.sync.client.connect(streamer.drive):
                pass

    assert telemetry_feed.peak_connections == 1


def test_drivers_that_come_and_go_share_one_car_connection(
    streamer: StreamerEndpoints, car_control: CarEndpointSpy
) -> None:
    for _ in range(_CLIENTS_THAT_COME_AND_GO):
        with websockets.sync.client.connect(streamer.drive):
            pass

    assert car_control.peak_connections == 1


def test_a_viewer_that_stops_reading_does_not_stall_another(
    camera_feed: CarEndpointSpy,
    telemetry_feed: CarEndpointSpy,
    car_control: CarEndpointSpy,
) -> None:
    with (
        _streamer(
            camera_feed,
            telemetry_feed,
            car_control,
            process_camera_frame=lambda jpeg: jpeg + _LARGE_FRAME_PADDING,
        ) as streamer,
        _viewer_that_stops_reading(streamer.camera),
        _viewer(streamer.camera) as viewer,
    ):
        for _ in range(_WARM_UP_PARTS):
            read_mjpeg_part(viewer.response)

        assert _parts_within(viewer, _READING_WINDOW_S) >= _MIN_PARTS_IN_WINDOW
