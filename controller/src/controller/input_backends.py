"""Input backends: sources of driving commands for the gamepad CLI."""

import curses
import time
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self

from pydualsense import pydualsense
from pydualsense.pydualsense import DSState

from .command import Command, DriveCommand


class InputBackendName(StrEnum):
    """Name of an input backend the controller can drive the car with."""

    DUALSENSE = "dualsense"
    KEYBOARD = "keyboard"


class InputBackend(Protocol):
    """Source of driving commands, polled once per control loop iteration."""

    def poll(self) -> DriveCommand | None:
        """Return the current command and value, or `None` to exit the control loop."""
        ...


def interpolate(
    value: float, in_min: float, in_max: float, out_min: float, out_max: float
) -> float:
    """Interpolate value from [in_min, in_max] range to [out_min, out_max] range."""
    return (value - in_min) * (out_max - out_min) / (in_max - in_min) + out_min


class DualSenseInputBackend:
    """Poll a DualSense controller for the current command and value.

    Use as a context manager: connects to the controller on entry, closes
    on exit. Constructs its own `pydualsense` handle unless one is given
    (for tests).
    """

    def __init__(
        self, ds: pydualsense | None = None, analog_dead_zone: int = 5
    ) -> None:
        """Initialize the object."""
        self._ds = ds if ds is not None else pydualsense()
        self._analog_dead_zone = analog_dead_zone

    def __enter__(self) -> Self:
        """Connect to the DualSense controller."""
        self._ds.init()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: TracebackType | None,
    ) -> None:
        """Disconnect from the DualSense controller."""
        self._ds.close()

    def poll(self) -> DriveCommand | None:
        """Return the current command/value, or `None` if the PS button was pressed."""
        # pydualsense reads reports on its own thread; this paces reading its state.
        poll_interval_s = 0.016
        time.sleep(poll_interval_s)
        return command_from_dualsense(self._ds.state, self._analog_dead_zone)


def command_from_dualsense(
    state: DSState, analog_dead_zone: int = 5
) -> DriveCommand | None:
    """Return the command and value `state` asks for, or `None` to quit."""
    if state.ps:
        return None
    return _held_command(state, analog_dead_zone)


def _held_command(state: DSState, analog_dead_zone: int) -> DriveCommand:
    command = Command.BRAKE
    value = None

    if state.DpadUp > 0:
        command, value = Command.ADVANCE, 50
    elif state.DpadRight:
        command, value = Command.TURN_RIGHT, 50
    elif state.DpadDown:
        command, value = Command.RETREAT, 50
    elif state.DpadLeft:
        command, value = Command.TURN_LEFT, 50
    elif not (-analog_dead_zone <= state.LX <= analog_dead_zone):
        if state.LX < 0:
            command = Command.TURN_LEFT
            value = int(interpolate(state.LX, -128, 0, 100, 0))
        else:
            command = Command.TURN_RIGHT
            value = int(interpolate(state.LX, 0, 127, 0, 100))
    elif not (-analog_dead_zone <= state.RX <= analog_dead_zone):
        command = Command.LOOK_HORIZONTALLY
        value = int(interpolate(state.RX, -128, 127, -90, 90))
    elif not (-analog_dead_zone <= state.RY <= analog_dead_zone):
        command = Command.LOOK_VERTICALLY
        value = int(interpolate(state.RY, -128, 127, 90, -90))
    elif state.R2 > 0:
        command = Command.ADVANCE
        value = int(interpolate(state.R2, 0, 255, 0, 100))

    return command, value


# Fixed values, mirroring the DualSense D-pad's existing fixed-value convention
# rather than analog interpolation.
_KEYBOARD_BINDINGS: dict[int, tuple[Command, int]] = {
    ord("w"): (Command.ADVANCE, 50),
    ord("s"): (Command.RETREAT, 50),
    ord("a"): (Command.TURN_LEFT, 50),
    ord("d"): (Command.TURN_RIGHT, 50),
    curses.KEY_LEFT: (Command.LOOK_HORIZONTALLY, -45),
    curses.KEY_RIGHT: (Command.LOOK_HORIZONTALLY, 45),
    curses.KEY_UP: (Command.LOOK_VERTICALLY, 45),
    curses.KEY_DOWN: (Command.LOOK_VERTICALLY, -45),
}
_KEYBOARD_EXIT_KEY = ord("q")

# Must exceed the host's initial key-repeat delay (500 ms on Ubuntu). A held
# key delivers one keydown, then nothing until auto-repeat starts; a timeout
# shorter than that gap reads the silence as a released key and emits BRAKE,
# so the car stutters for the whole delay before the repeats sustain it.
#
# The timeout is therefore also the shortest command the backend can express:
# a tap holds its command for this long before BRAKE follows. Shortening it
# below the host's repeat delay brings the stutter back; the way to a finer
# minimum is to lower that delay (`xset r rate`) and this timeout together.
_KEYBOARD_POLL_TIMEOUT_MS = 600


class _InputWindow(Protocol):
    """The subset of `curses.window` the keyboard backend reads through.

    A structural type rather than `curses.window` itself, so tests can pass
    a stub instead of a real (C-extension) curses window.
    """

    # `timeout` and `getch` mirror curses.window's C functions, which only
    # accept positional arguments.
    def timeout(self, delay: int, /) -> None: ...
    def getch(self) -> int: ...


class KeyboardInputBackend:
    """Poll a terminal keyboard for the current command and value.

    Uses a timed-out `curses` read, so a key that isn't held down (or isn't
    being auto-repeated by the terminal within the poll timeout) reads back
    as `BRAKE`, mirroring the DualSense analog sticks' spring-back-to-center
    behavior. The timeout also bounds how long the exit key takes to
    register.
    """

    def __init__(
        self, window: _InputWindow, poll_timeout_ms: int = _KEYBOARD_POLL_TIMEOUT_MS
    ) -> None:
        """Initialize the object."""
        self._window = window
        self._window.timeout(poll_timeout_ms)

    def poll(self) -> DriveCommand | None:
        """Return the current command and value, or `None` if 'q' was pressed."""
        return command_from_key(self._window.getch())


def command_from_key(key: int) -> DriveCommand | None:
    """Return the command and value `key` asks for, or `None` to quit."""
    if key == _KEYBOARD_EXIT_KEY:
        return None
    return _KEYBOARD_BINDINGS.get(key, (Command.BRAKE, None))
