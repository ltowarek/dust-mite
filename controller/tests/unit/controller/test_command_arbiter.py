from typing import Any

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from controller.car import Message
from controller.collision_monitor import CollisionMonitor
from controller.command import Command
from controller.command_arbiter import (
    DRIVER_ALREADY_CONNECTED,
    CommandArbiter,
    DriverAlreadyConnectedError,
)
from controller.subject import Subject
from tests.test_doubles import SubscriberSpy

from .conftest import counter_values_by_command

_SPEED = 50
_CLEAR_DISTANCE_CM = 100
_OBSTACLE_DISTANCE_CM = 3


class _Car:
    """The arbiter's surroundings: a telemetry source and the commands it publishes."""

    def __init__(self) -> None:
        self.telemetry = Subject[Message]()
        self.commands = Subject[Message]()
        self.sent = SubscriberSpy[dict[str, Any]]()
        self.collision_states = SubscriberSpy[dict[str, Any]]()
        self.arbiter = CommandArbiter(self.commands, self.telemetry, CollisionMonitor())

    def report_distance(self, distance_ahead_cm: int) -> None:
        self.telemetry.publish(
            {"type": "telemetry", "data": {"distance_ahead": distance_ahead_cm}}
        )


@pytest.fixture
def car() -> _Car:
    return _Car()


def _command(command: Command) -> dict[str, Any]:
    return {"command": command.value, "value": _SPEED}


def test_refuses_a_second_claim(car: _Car) -> None:
    with (
        car.arbiter.claim(),
        pytest.raises(DriverAlreadyConnectedError, match=DRIVER_ALREADY_CONNECTED),
        car.arbiter.claim(),
    ):
        pass


def test_accepts_a_claim_after_the_previous_one_is_released(car: _Car) -> None:
    with car.arbiter.claim():
        pass

    with car.commands.subscription(car.sent), car.arbiter.claim() as submit:
        submit(_command(Command.TURN_LEFT))

    assert car.sent.messages[0]["command"] == Command.TURN_LEFT.value


def test_publishes_a_command_while_the_way_is_clear(car: _Car) -> None:
    with car.commands.subscription(car.sent), car.arbiter.claim() as submit:
        car.report_distance(_CLEAR_DISTANCE_CM)
        submit(_command(Command.ADVANCE))

    assert car.sent.messages[0]["command"] == Command.ADVANCE.value


def test_brakes_instead_of_advancing_into_an_obstacle(car: _Car) -> None:
    with car.commands.subscription(car.sent), car.arbiter.claim() as submit:
        car.report_distance(_OBSTACLE_DISTANCE_CM)
        submit(_command(Command.ADVANCE))

    assert car.sent.messages[0]["command"] == Command.BRAKE.value


def test_counts_an_advance_it_blocks(car: _Car, reader: InMemoryMetricReader) -> None:
    with car.arbiter.claim() as submit:
        car.report_distance(_OBSTACLE_DISTANCE_CM)
        submit(_command(Command.ADVANCE))

    assert counter_values_by_command(reader, "dust_mite_commands_blocked") == {
        Command.ADVANCE.name: 1
    }


def test_ignores_telemetry_while_no_driver_holds_it(car: _Car) -> None:
    car.report_distance(_OBSTACLE_DISTANCE_CM)

    with car.commands.subscription(car.sent), car.arbiter.claim() as submit:
        submit(_command(Command.ADVANCE))

    assert car.sent.messages[0]["command"] == Command.ADVANCE.value


def test_publishes_when_the_collision_monitor_starts_stopping(car: _Car) -> None:
    with (
        car.arbiter.collision_state.subscription(car.collision_states),
        car.arbiter.claim(),
    ):
        car.report_distance(_OBSTACLE_DISTANCE_CM)

    assert car.collision_states.messages[0]["stopping"] is True


def test_clears_the_collision_state_when_the_driver_leaves(car: _Car) -> None:
    with (
        car.arbiter.collision_state.subscription(car.collision_states),
        car.arbiter.claim(),
    ):
        car.report_distance(_OBSTACLE_DISTANCE_CM)

    assert car.collision_states.messages[-1]["stopping"] is False
