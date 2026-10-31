"""When the CLI sends Drive commands: the timing of the web page's drive controller."""

import dataclasses
from typing import assert_never

from .command import Command, DriveCommand


@dataclasses.dataclass(frozen=True)
class Parked:
    """Nothing is held, so nothing is sent."""


@dataclasses.dataclass(frozen=True)
class Driving:
    """A control is held: `command` is resent at `resend_at`."""

    command: DriveCommand
    resend_at: float


@dataclasses.dataclass(frozen=True)
class Tick:
    """The resend timer fired."""


type SendState = Parked | Driving
type Event = DriveCommand | Tick


def transition(
    state: SendState, event: Event, now: float
) -> tuple[SendState, list[DriveCommand]]:
    """Return the state after `event` at `now`, and the Drive commands to send."""
    # Well under the car's drive-command watchdog.
    resend_interval_s = 0.1
    match state:
        case Parked():
            match event:
                # A reading of BRAKE means nothing is held.
                case Tick() | (Command.BRAKE, _):
                    return state, []
                case reading:
                    return Driving(reading, now + resend_interval_s), [reading]
        case Driving(command=held, resend_at=resend_at):
            match event:
                case Tick():
                    return Driving(held, now + resend_interval_s), [held]
                case (Command.BRAKE, _):
                    return Parked(), [(Command.BRAKE, None)]
                case reading:
                    return Driving(reading, resend_at), []
        case _:
            assert_never(state)


def resend_due(state: SendState) -> float | None:
    """Return when the next resend is due, or `None` if none is."""
    match state:
        case Driving(resend_at=resend_at):
            return resend_at
        case Parked():
            return None
        case _:
            assert_never(state)
