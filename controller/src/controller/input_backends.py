"""Input backends: sources of driving commands for the gamepad CLI."""

import contextlib
import curses
from collections.abc import Iterator
from enum import StrEnum
from typing import Protocol

from pydualsense import pydualsense

from .command import Command


class InputBackendName(StrEnum):
    """Value of the `CONTROLLER_INPUT_BACKEND` environment variable."""

    DUALSENSE = "dualsense"
    KEYBOARD = "keyboard"


class InputBackend(Protocol):
    """Source of driving commands, polled once per control loop iteration."""

    def poll(self) -> tuple[Command, int | None] | None:
        """Return the current command and value, or `None` to exit the control loop."""
        ...


def interpolate(
    value: float, in_min: float, in_max: float, out_min: float, out_max: float
) -> float:
    """Interpolate value from [in_min, in_max] range to [out_min, out_max] range."""
    return (value - in_min) * (out_max - out_min) / (in_max - in_min) + out_min


class DualSenseInputBackend:
    """Poll a DualSense controller for the current command and value."""

    def __init__(self, ds: pydualsense, analog_dead_zone: int = 5) -> None:
        """Initialize the object."""
        self._ds = ds
        self._analog_dead_zone = analog_dead_zone

    def poll(self) -> tuple[Command, int | None] | None:
        """Return the current command/value, or `None` if the PS button was pressed."""
        if self._ds.state.ps:
            return None
        return self._read_state()

    def _read_state(self) -> tuple[Command, int | None]:
        ds = self._ds
        analog_dead_zone = self._analog_dead_zone
        command = Command.BRAKE
        value = None

        # TODO: Split car and camera commands
        # Currently there is no way to drive a car and look around
        # What's more, you can't look horizontally and vertically and the same time
        if ds.state.DpadUp > 0:
            command, value = Command.ADVANCE, 50
        elif ds.state.DpadRight:
            command, value = Command.TURN_RIGHT, 50
        elif ds.state.DpadDown:
            command, value = Command.RETREAT, 50
        elif ds.state.DpadLeft:
            command, value = Command.TURN_LEFT, 50
        elif not (-analog_dead_zone <= ds.state.LX <= analog_dead_zone):
            if ds.state.LX < 0:
                command = Command.TURN_LEFT
                value = int(interpolate(ds.state.LX, -128, 0, 100, 0))
            else:
                command = Command.TURN_RIGHT
                value = int(interpolate(ds.state.LX, 0, 127, 0, 100))
        elif not (-analog_dead_zone <= ds.state.RX <= analog_dead_zone):
            command = Command.LOOK_HORIZONTALLY
            value = int(interpolate(ds.state.RX, -128, 127, -90, 90))
        elif not (-analog_dead_zone <= ds.state.RY <= analog_dead_zone):
            command = Command.LOOK_VERTICALLY
            value = int(interpolate(ds.state.RY, -128, 127, 90, -90))
        elif ds.state.R2 > 0:
            command = Command.ADVANCE
            value = int(interpolate(ds.state.R2, 0, 255, 0, 100))

        return command, value


class _CursesWindow(Protocol):
    """Minimal curses window interface used by `KeyboardInputBackend`."""

    def timeout(self, delay: int) -> None: ...

    def getch(self) -> int: ...


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

# Wide enough to catch the terminal's next auto-repeated keydown while a key
# is held, so a held key doesn't flicker back to BRAKE between repeats.
_KEYBOARD_POLL_TIMEOUT_MS = 50


class KeyboardInputBackend:
    """Poll a terminal keyboard for the current command and value.

    Uses a timed-out `curses` read, so a key that isn't held down (or isn't
    being auto-repeated by the terminal within the poll timeout) reads back
    as `BRAKE`, mirroring the DualSense analog sticks' spring-back-to-center
    behavior.
    """

    def __init__(self, window: _CursesWindow) -> None:
        """Initialize the object."""
        self._window = window
        self._window.timeout(_KEYBOARD_POLL_TIMEOUT_MS)

    def poll(self) -> tuple[Command, int | None] | None:
        """Return the current command and value, or `None` if 'q' was pressed."""
        key = self._window.getch()
        if key == _KEYBOARD_EXIT_KEY:
            return None
        if key in _KEYBOARD_BINDINGS:
            return _KEYBOARD_BINDINGS[key]
        return Command.BRAKE, None


@contextlib.contextmanager
def _curses_session() -> Iterator[_CursesWindow]:
    """Initialize curses and guarantee terminal restoration on exit.

    Mirrors `curses.wrapper`'s setup/teardown sequence, but as a context
    manager spanning a backend's lifetime instead of a single wrapped
    function call.
    """
    window = curses.initscr()
    try:
        curses.noecho()
        curses.cbreak()
        window.keypad(True)  # noqa: FBT003 - curses' C API is positional-only
        with contextlib.suppress(curses.error):
            # Harmless if the terminal doesn't have color; matches
            # `curses.wrapper`'s own use of `start_color`.
            curses.start_color()
        yield window
    finally:
        window.keypad(False)  # noqa: FBT003 - curses' C API is positional-only
        curses.echo()
        curses.nocbreak()
        curses.endwin()


@contextlib.contextmanager
def create_input_backend(name: InputBackendName) -> Iterator[InputBackend]:
    """Construct and manage the lifecycle of the named input backend."""
    if name is InputBackendName.KEYBOARD:
        with _curses_session() as window:
            yield KeyboardInputBackend(window)
        return

    ds = pydualsense()
    ds.init()
    try:
        yield DualSenseInputBackend(ds)
    finally:
        ds.close()
