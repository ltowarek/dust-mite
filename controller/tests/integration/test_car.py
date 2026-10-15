import http
import json
from typing import Any

import websockets.http11
import websockets.sync.server

from controller.car import CarFeed, send_commands_to_car
from controller.command import Command
from controller.subject import Subject
from tests.test_doubles import SubscriberSpy

from .test_doubles import CarEndpointSpy, camera_frame, car_feed_stub
from .waiting import wait_for

_SPEED = 50


def test_feed_subscribers_share_one_car_connection(
    camera_feed: CarEndpointSpy,
) -> None:
    feed = CarFeed(camera_feed.uri, json.loads)
    first, second = SubscriberSpy[dict[str, Any]](), SubscriberSpy[dict[str, Any]]()

    with feed.subscription(first), feed.subscription(second):
        wait_for(lambda: bool(first.messages and second.messages))

    assert camera_feed.peak_connections == 1


def test_feed_disconnects_after_the_last_subscriber_leaves(
    camera_feed: CarEndpointSpy,
) -> None:
    feed = CarFeed(camera_feed.uri, json.loads)
    recorder = SubscriberSpy[dict[str, Any]]()

    with feed.subscription(recorder):
        wait_for(lambda: bool(recorder.messages))

    assert wait_for(lambda: camera_feed.open_connections == 0)


def test_feed_retries_while_the_car_refuses_as_busy() -> None:
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

    recorder = SubscriberSpy[dict[str, Any]]()
    with car_feed_stub(camera_frame, process_request=refuse_first) as camera:
        feed = CarFeed(camera.uri, json.loads)
        with feed.subscription(recorder):
            assert wait_for(lambda: bool(recorder.messages))

    assert refusals == 0


def test_opens_the_control_connection_at_once(car_control: CarEndpointSpy) -> None:
    with send_commands_to_car(car_control.uri, Subject()):
        assert wait_for(lambda: car_control.open_connections == 1)


def test_sends_each_published_command_to_the_car(
    car_control: CarEndpointSpy,
) -> None:
    commands = Subject[dict[str, Any]]()
    command = {"command": Command.ADVANCE.value, "value": _SPEED}

    with send_commands_to_car(car_control.uri, commands):
        commands.publish(command)
        wait_for(lambda: bool(car_control.received))

    assert car_control.received == [command]
