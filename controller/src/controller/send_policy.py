"""When the CLI sends Drive commands: the timing of the web page's drive controller."""

import dataclasses

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
    if isinstance(event, Tick):
        if isinstance(state, Parked):
            return state, []
        return Driving(state.command, now + resend_interval_s), [state.command]
    # A reading of BRAKE means nothing is held.
    held = event[0] is not Command.BRAKE
    if isinstance(state, Parked):
        if not held:
            return state, []
        return Driving(event, now + resend_interval_s), [event]
    if not held:
        return Parked(), [(Command.BRAKE, None)]
    return Driving(event, state.resend_at), []
