"""Guards the CLI's Drive command autorepeat, which mirrors the web page's."""

import dataclasses

import pytest

from controller.autorepeat import Driving, Event, Parked, SendState, Tick, transition
from controller.command import Command, DriveCommand

_ADVANCE: DriveCommand = (Command.ADVANCE, 50)
_BRAKE: DriveCommand = (Command.BRAKE, None)


@dataclasses.dataclass(frozen=True)
class Transition:
    state: SendState
    event: Event
    now: float
    next_state: SendState
    sent: list[DriveCommand]


_TRANSITIONS = [
    pytest.param(
        Transition(
            Parked(),
            _ADVANCE,
            0.0,
            Driving(_ADVANCE, resend_at=0.1),
            [_ADVANCE],
        ),
        id="parked_to_driving",
    ),
    pytest.param(
        Transition(
            Driving(_ADVANCE, resend_at=0.1),
            Tick(),
            0.1,
            Driving(_ADVANCE, resend_at=0.2),
            [_ADVANCE],
        ),
        id="tick_while_driving",
    ),
    pytest.param(
        Transition(
            Driving((Command.TURN_LEFT, 30), resend_at=0.1),
            (Command.TURN_LEFT, 60),
            0.05,
            Driving((Command.TURN_LEFT, 60), resend_at=0.1),
            [],
        ),
        id="value_change_while_driving",
    ),
    pytest.param(
        Transition(
            Driving(_ADVANCE, resend_at=0.1),
            _ADVANCE,
            0.05,
            Driving(_ADVANCE, resend_at=0.1),
            [],
        ),
        id="same_reading_while_driving",
    ),
    pytest.param(
        Transition(
            Driving(_ADVANCE, resend_at=0.1),
            _BRAKE,
            0.05,
            Parked(),
            [_BRAKE],
        ),
        id="driving_to_parked",
    ),
    pytest.param(
        Transition(Parked(), Tick(), 0.1, Parked(), []), id="tick_while_parked"
    ),
    pytest.param(
        Transition(Parked(), _BRAKE, 0.1, Parked(), []), id="brake_while_parked"
    ),
]


@pytest.mark.parametrize("case", _TRANSITIONS)
def test_sends(case: Transition) -> None:
    _, sent = transition(case.state, case.event, case.now)

    assert sent == case.sent


@pytest.mark.parametrize("case", _TRANSITIONS)
def test_moves_to(case: Transition) -> None:
    next_state, _ = transition(case.state, case.event, case.now)

    assert next_state == case.next_state
