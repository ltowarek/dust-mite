import json
from typing import Any

from controller.car import CarFeed, send_commands_to_car
from controller.command import Command
from controller.subject import Subject

from .car_doubles import CarEndpointSpy, wait_for

_SPEED = 50


class _Recorder:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def __call__(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


def test_feed_subscribers_share_one_car_connection(
    camera_feed: CarEndpointSpy,
) -> None:
    feed = CarFeed(camera_feed.uri, json.loads)
    first, second = _Recorder(), _Recorder()

    with feed.subscription(first), feed.subscription(second):
        wait_for(lambda: bool(first.messages and second.messages))

    assert camera_feed.peak_connections == 1


def test_feed_disconnects_after_the_last_subscriber_leaves(
    camera_feed: CarEndpointSpy,
) -> None:
    feed = CarFeed(camera_feed.uri, json.loads)
    recorder = _Recorder()

    with feed.subscription(recorder):
        wait_for(lambda: bool(recorder.messages))

    assert wait_for(lambda: camera_feed.open_connections == 0)


def test_opens_the_control_connection_at_once(car_control: CarEndpointSpy) -> None:
    with send_commands_to_car(car_control.uri, Subject()):
        assert wait_for(lambda: car_control.open_connections == 1)


def test_sends_each_published_command_to_the_car(
    car_control: CarEndpointSpy,
) -> None:
    commands = Subject()
    command = {"command": Command.ADVANCE.value, "value": _SPEED}

    with send_commands_to_car(car_control.uri, commands):
        commands.publish(command)
        wait_for(lambda: bool(car_control.received))

    assert car_control.received == [command]
