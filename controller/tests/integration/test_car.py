import functools
import http
import json

import websockets.http11
import websockets.sync.server

from controller.car import CarFeed, send_commands_to_car
from controller.command import Command
from controller.mjpeg import CameraStreamPart, MjpegClient
from controller.subject import Subject
from controller.websocket_client import WebSocketClient
from controller.websocket_message import WebSocketMessage
from tests.test_doubles import SubscriberSpy

from .test_doubles import (
    CAR_TRACEPARENT,
    CLEAR_DISTANCE_CM,
    CarEndpointSpy,
    car_camera_stub,
    car_feed_stub,
    telemetry,
)
from .waiting import wait_for

_SPEED = 50


def _camera(endpoint: CarEndpointSpy) -> CarFeed[CameraStreamPart, WebSocketMessage]:
    return CarFeed(functools.partial(MjpegClient, endpoint.uri), lambda p: p.headers)


def test_camera_feed_publishes_each_part_from_the_car(
    camera_feed: CarEndpointSpy,
) -> None:
    recorder = SubscriberSpy[WebSocketMessage]()

    with _camera(camera_feed).subscription(recorder):
        wait_for(lambda: bool(recorder.messages))

    assert recorder.messages[0]["traceparent"] == CAR_TRACEPARENT


def test_feed_subscribers_share_one_car_connection(
    camera_feed: CarEndpointSpy,
) -> None:
    feed = _camera(camera_feed)
    first, second = SubscriberSpy[WebSocketMessage](), SubscriberSpy[WebSocketMessage]()

    with feed.subscription(first), feed.subscription(second):
        wait_for(lambda: bool(first.messages and second.messages))

    assert camera_feed.peak_connections == 1


def test_feed_disconnects_after_the_last_subscriber_leaves(
    camera_feed: CarEndpointSpy,
) -> None:
    recorder = SubscriberSpy[WebSocketMessage]()

    with _camera(camera_feed).subscription(recorder):
        wait_for(lambda: bool(recorder.messages))

    assert wait_for(lambda: camera_feed.open_connections == 0)


def test_camera_feed_retries_while_the_car_refuses_as_busy() -> None:
    recorder = SubscriberSpy[WebSocketMessage]()

    with car_camera_stub(refusals=1) as camera, _camera(camera).subscription(recorder):
        assert wait_for(lambda: bool(recorder.messages))


def test_telemetry_feed_retries_while_the_car_refuses_as_busy() -> None:
    refusals = 1

    def refuse_first(
        connection: websockets.sync.server.ServerConnection,
        _: websockets.http11.Request,
    ) -> websockets.http11.Response | None:
        nonlocal refusals
        if refusals > 0:
            refusals -= 1
            return connection.respond(http.HTTPStatus.SERVICE_UNAVAILABLE, "")
        return None

    recorder = SubscriberSpy[WebSocketMessage]()
    stub = car_feed_stub(telemetry(CLEAR_DISTANCE_CM), process_request=refuse_first)
    with stub as car:
        feed = CarFeed(functools.partial(WebSocketClient, car.uri, "r"), json.loads)
        with feed.subscription(recorder):
            assert wait_for(lambda: bool(recorder.messages))


def test_opens_the_control_connection_at_once(car_control: CarEndpointSpy) -> None:
    with send_commands_to_car(car_control.uri, Subject()):
        assert wait_for(lambda: car_control.open_connections == 1)


def test_sends_each_published_command_to_the_car(
    car_control: CarEndpointSpy,
) -> None:
    commands = Subject[WebSocketMessage]()
    command = {"command": Command.ADVANCE.value, "value": _SPEED}

    with send_commands_to_car(car_control.uri, commands):
        commands.publish(command)
        wait_for(lambda: bool(car_control.received))

    assert car_control.received == [command]
