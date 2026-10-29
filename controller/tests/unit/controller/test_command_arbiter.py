import asyncio
from typing import Any

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from controller.collision_monitor import CollisionMonitor
from controller.command import Command
from controller.command_arbiter import (
    DRIVER_ALREADY_CONNECTED,
    CommandArbiter,
    DriverAlreadyConnectedError,
)
from controller.outbox import Broadcast, Outbox
from controller.websocket_message import WebSocketMessage

from .conftest import counter_values_by_command

_SPEED = 50
_CLEAR_DISTANCE_CM = 100
_OBSTACLE_DISTANCE_CM = 3


class _Car:
    """The arbiter's surroundings: a telemetry source and the commands it publishes."""

    def __init__(self) -> None:
        self.telemetry = Broadcast[WebSocketMessage]()
        self.commands = Broadcast[WebSocketMessage]()
        self.sent = Outbox(self.commands)
        self.arbiter = CommandArbiter(self.commands, self.telemetry, CollisionMonitor())
        self.collision_states = Outbox(self.arbiter.collision_state)

    def report_distance(self, distance_ahead_cm: int) -> None:
        self.telemetry.publish(
            {"type": "telemetry", "data": {"distance_ahead": distance_ahead_cm}}
        )


@pytest.fixture
def car() -> _Car:
    return _Car()


def _command(command: Command) -> dict[str, Any]:
    return {"command": command.value, "value": _SPEED}


@pytest.mark.asyncio
async def test_refuses_a_second_claim(car: _Car) -> None:
    async with car.arbiter.claim():
        with pytest.raises(DriverAlreadyConnectedError, match=DRIVER_ALREADY_CONNECTED):
            async with car.arbiter.claim():
                pass


@pytest.mark.asyncio
async def test_accepts_a_claim_after_the_previous_one_is_released(car: _Car) -> None:
    async with car.arbiter.claim():
        pass

    async with car.sent, car.arbiter.claim() as submit:
        submit(_command(Command.TURN_LEFT))

        assert (await anext(car.sent))["command"] == Command.TURN_LEFT.value


@pytest.mark.asyncio
async def test_publishes_a_command_while_the_way_is_clear(car: _Car) -> None:
    async with car.sent, car.arbiter.claim() as submit:
        car.report_distance(_CLEAR_DISTANCE_CM)
        submit(_command(Command.ADVANCE))

        assert (await anext(car.sent))["command"] == Command.ADVANCE.value


@pytest.mark.asyncio
async def test_brakes_instead_of_advancing_into_an_obstacle(car: _Car) -> None:
    async with car.collision_states, car.sent, car.arbiter.claim() as submit:
        car.report_distance(_OBSTACLE_DISTANCE_CM)
        await anext(car.collision_states)
        submit(_command(Command.ADVANCE))

        assert (await anext(car.sent))["command"] == Command.BRAKE.value


@pytest.mark.asyncio
async def test_counts_an_advance_it_blocks(
    car: _Car, reader: InMemoryMetricReader
) -> None:
    async with car.collision_states, car.arbiter.claim() as submit:
        car.report_distance(_OBSTACLE_DISTANCE_CM)
        await anext(car.collision_states)
        submit(_command(Command.ADVANCE))

    assert counter_values_by_command(reader, "dust_mite_commands_blocked") == {
        Command.ADVANCE.name: 1
    }


@pytest.mark.asyncio
async def test_ignores_telemetry_while_no_driver_holds_it(car: _Car) -> None:
    car.report_distance(_OBSTACLE_DISTANCE_CM)

    async with car.sent, car.arbiter.claim() as submit:
        submit(_command(Command.ADVANCE))

        assert (await anext(car.sent))["command"] == Command.ADVANCE.value


@pytest.mark.asyncio
async def test_publishes_when_the_collision_monitor_starts_stopping(car: _Car) -> None:
    async with car.collision_states, car.arbiter.claim():
        car.report_distance(_OBSTACLE_DISTANCE_CM)

        assert (await anext(car.collision_states))["stopping"] is True


@pytest.mark.asyncio
async def test_clears_the_collision_state_when_the_driver_leaves(car: _Car) -> None:
    async with car.collision_states:
        async with car.arbiter.claim():
            car.report_distance(_OBSTACLE_DISTANCE_CM)
            await anext(car.collision_states)

        assert (await anext(car.collision_states))["stopping"] is False


@pytest.mark.asyncio
async def test_brakes_after_an_obstacle_reported_just_before_a_further_reading(
    car: _Car,
) -> None:
    between_stop_and_resume_cm = 7
    async with car.collision_states, car.sent, car.arbiter.claim() as submit:
        car.report_distance(_OBSTACLE_DISTANCE_CM)
        car.report_distance(between_stop_and_resume_cm)
        # A missed obstacle publishes nothing, so the wait is bounded.
        async with asyncio.timeout(1):
            await anext(car.collision_states)
        submit(_command(Command.ADVANCE))

        assert (await anext(car.sent))["command"] == Command.BRAKE.value
