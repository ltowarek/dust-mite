"""Input backends: sources of driving commands for the gamepad CLI."""

import asyncio
import curses
from collections.abc import Callable
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
    """Source of the Driver's input readings."""

    async def read(self, publish: Callable[[DriveCommand], None]) -> None:
        """Publish each input reading until the Driver quits."""
        ...


def interpolate(
    value: float, in_min: float, in_max: float, out_min: float, out_max: float
) -> float:
    """Interpolate value from [in_min, in_max] range to [out_min, out_max] range."""
    return (value - in_min) * (out_max - out_min) / (in_max - in_min) + out_min


class DualSenseInputBackend:
    """Publish a DualSense controller's input readings as it reports changes.

    Use as an async context manager: connects to the controller on entry,
    closes on exit. Constructs its own `pydualsense` handle unless one is
    given (for tests).
    """

    def __init__(
        self, ds: pydualsense | None = None, analog_dead_zone: int = 5
    ) -> None:
        """Initialize the object."""
        self._ds = ds if ds is not None else pydualsense()
        self._analog_dead_zone = analog_dead_zone

    async def __aenter__(self) -> Self:
        """Connect to the DualSense controller."""
        await asyncio.to_thread(self._ds.init)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: TracebackType | None,
    ) -> None:
        """Disconnect, stopping the report thread before the event loop closes."""
        await asyncio.to_thread(self._ds.close)

    async def read(self, publish: Callable[[DriveCommand], None]) -> None:
        """Publish the input reading of each change the controller reports, until PS.

        Nothing is published before the first change: until pydualsense
        parses its first report, which fires no events, `state` is a
        placeholder that reads as TURN_RIGHT 100.
        """
        loop = asyncio.get_running_loop()
        ps_pressed = asyncio.Event()

        def on_change(*_: object) -> None:
            # Runs on pydualsense's report thread, after the whole report is written.
            state = self._ds.state
            if state.ps:
                loop.call_soon_threadsafe(ps_pressed.set)
            else:
                reading = command_from_dualsense(state, self._analog_dead_zone)
                loop.call_soon_threadsafe(publish, reading)

        ds = self._ds
        events = (
            ds.dpad_up,
            ds.dpad_down,
            ds.dpad_left,
            ds.dpad_right,
            ds.left_joystick_changed,
            ds.right_joystick_changed,
            ds.r2_changed,
            ds.ps_pressed,
        )
        for event in events:
            event.subscribe(on_change)
        try:
            await ps_pressed.wait()
        finally:
            for event in events:
                event.unsubscribe(on_change)


def command_from_dualsense(state: DSState, analog_dead_zone: int) -> DriveCommand:
    """Return the command and value `state` asks for."""
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
# key delivers one keydown, then nothing until key repeat starts; a timeout
# shorter than that gap reads the silence as a released key and emits BRAKE,
# so the car stutters for the whole delay before the repeats sustain it.
#
# The timeout is therefore also the shortest command the backend can express:
# a tap holds its command for this long before BRAKE follows. Shortening it
# below the host's repeat delay brings the stutter back; the way to a finer
# minimum is to lower that delay (`xset r rate`) and this timeout together.
_KEYBOARD_READ_TIMEOUT_MS = 600


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
    """Read a terminal keyboard for the current command and value.

    Uses a timed-out `curses` read, so a key that isn't held down (or isn't
    repeated by the terminal's key repeat within the read timeout) reads
    back as `BRAKE`, mirroring the DualSense analog sticks'
    spring-back-to-center behavior. The timeout also bounds how long the
    exit key takes to register.
    """

    def __init__(
        self,
        window: _InputWindow,
        write_queued_logs: Callable[[], None] = lambda: None,
        read_timeout_ms: int = _KEYBOARD_READ_TIMEOUT_MS,
    ) -> None:
        """Initialize the object; `write_queued_logs` runs between key reads."""
        self._window = window
        self._write_queued_logs = write_queued_logs
        self._window.timeout(read_timeout_ms)

    async def read(self, publish: Callable[[DriveCommand], None]) -> None:
        """Publish each key's input reading until 'q' is pressed."""
        while True:
            self._write_queued_logs()
            key = await asyncio.to_thread(self._window.getch)
            if key == _KEYBOARD_EXIT_KEY:
                return
            publish(command_from_key(key))


def command_from_key(key: int) -> DriveCommand:
    """Return the command and value `key` asks for."""
    return _KEYBOARD_BINDINGS.get(key, (Command.BRAKE, None))
