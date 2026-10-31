import asyncio
import curses

import pytest
from pydualsense import pydualsense
from pydualsense.pydualsense import DSState

from controller.command import Command, DriveCommand
from controller.input_backends import (
    _KEYBOARD_POLL_TIMEOUT_MS,
    DualSenseInputBackend,
    KeyboardInputBackend,
    command_from_dualsense,
    command_from_key,
)

# `curses.getch` returns -1 (ERR) when the poll timeout lapses with no key.
_CURSES_ERR = -1


def _dualsense_state(**state_overrides: bool | int) -> DSState:
    """Build a `DSState` at rest, with the given fields set."""
    state = DSState()
    # DSState()'s raw LX/RX/RY/LY default (128) is an unpopulated
    # placeholder, not a real reading: `readInput()` normalizes a real
    # report to `raw_byte - 128`, so 0 is what an at-rest stick reads as.
    state.LX = 0
    state.RX = 0
    state.RY = 0
    state.LY = 0
    for name, value in state_overrides.items():
        setattr(state, name, value)
    return state


class TestCommandFromDualSense:
    def test_ps_button_quits(self) -> None:
        assert command_from_dualsense(_dualsense_state(ps=True)) is None

    @pytest.mark.parametrize(
        ("state_overrides", "expected"),
        [
            pytest.param({}, (Command.BRAKE, None), id="no_input"),
            pytest.param({"DpadUp": True}, (Command.ADVANCE, 50), id="dpad_up"),
            pytest.param(
                {"DpadRight": True}, (Command.TURN_RIGHT, 50), id="dpad_right"
            ),
            pytest.param({"DpadDown": True}, (Command.RETREAT, 50), id="dpad_down"),
            pytest.param({"DpadLeft": True}, (Command.TURN_LEFT, 50), id="dpad_left"),
            pytest.param(
                {"LX": 5}, (Command.BRAKE, None), id="left_stick_within_dead_zone"
            ),
            pytest.param(
                {"LX": -128}, (Command.TURN_LEFT, 100), id="left_stick_negative"
            ),
            pytest.param(
                {"LX": 127}, (Command.TURN_RIGHT, 100), id="left_stick_positive"
            ),
            pytest.param(
                {"RX": 127}, (Command.LOOK_HORIZONTALLY, 90), id="right_stick_x"
            ),
            pytest.param(
                {"RY": -128}, (Command.LOOK_VERTICALLY, 90), id="right_stick_y"
            ),
            pytest.param({"R2": 255}, (Command.ADVANCE, 100), id="r2"),
        ],
    )
    def test_translates_state_to_command(
        self,
        state_overrides: dict[str, bool | int],
        expected: DriveCommand,
    ) -> None:
        assert command_from_dualsense(_dualsense_state(**state_overrides)) == expected


async def _start_reading(
    ds: pydualsense, published: list[DriveCommand]
) -> asyncio.Task[None]:
    """Start reading `ds` and return once its change events are subscribed."""
    reading = asyncio.create_task(DualSenseInputBackend(ds).read(published.append))
    await asyncio.sleep(0)
    return reading


async def _report(ds: pydualsense, event_name: str) -> None:
    """Fire `ds`'s change event `event_name` from a thread, as pydualsense does."""
    await asyncio.to_thread(getattr(ds, event_name))


class TestDualSenseInputBackend:
    @pytest.mark.parametrize(
        "event_name",
        [
            "dpad_up",
            "dpad_down",
            "dpad_left",
            "dpad_right",
            "left_joystick_changed",
            "right_joystick_changed",
            "r2_changed",
        ],
    )
    @pytest.mark.asyncio
    async def test_publishes_the_reading_of_a_change_event(
        self, event_name: str
    ) -> None:
        ds = pydualsense()
        ds.state = _dualsense_state()
        published: list[DriveCommand] = []
        reading = await _start_reading(ds, published)

        ds.state.DpadUp = True
        await _report(ds, event_name)
        ds.state.ps = True
        await _report(ds, "ps_pressed")
        await reading

        assert published == [(Command.ADVANCE, 50)]

    @pytest.mark.asyncio
    async def test_ps_ends_the_read(self) -> None:
        wait_s = 1.0
        ds = pydualsense()
        ds.state = _dualsense_state()
        reading = await _start_reading(ds, [])

        ds.state.ps = True
        await _report(ds, "ps_pressed")
        await asyncio.wait([reading], timeout=wait_s)

        assert reading.done()

    @pytest.mark.asyncio
    async def test_publishes_nothing_in_the_placeholder_state(self) -> None:
        """Before its first report, pydualsense's sticks read as TURN_RIGHT 100."""
        ds = pydualsense()
        ds.state = DSState()
        published: list[DriveCommand] = []
        reading = await _start_reading(ds, published)

        ds.state.ps = True
        await _report(ds, "ps_pressed")
        await reading

        assert published == []


class HeldKeyWindowStub:
    """Stub `curses.window` replaying one key held down under auto-repeat.

    A terminal delivers a held key as a single keydown, then nothing until
    the host's initial repeat delay elapses, then repeats at a steady
    interval. This reproduces that arrival pattern against a virtual clock
    driven by the poll timeout the backend installs, so the tests model the
    real timing without spending real time.
    """

    def __init__(
        self,
        key: int,
        *,
        repeat_delay_ms: int = 500,
        repeat_interval_ms: int = 30,
        hold_ms: int = 2000,
        reads: int = 20,
    ) -> None:
        self._arrivals = self._arrival_times(
            repeat_delay_ms, repeat_interval_ms, hold_ms
        )
        self._key = key
        self._reads_left = reads
        self._now_ms = 0
        self._timeout_ms = 0

    @staticmethod
    def _arrival_times(
        repeat_delay_ms: int, repeat_interval_ms: int, hold_ms: int
    ) -> list[int]:
        arrivals = [0]
        at = repeat_delay_ms
        while at <= hold_ms:
            arrivals.append(at)
            at += repeat_interval_ms
        return arrivals

    @property
    def elapsed_ms(self) -> int:
        """Virtual milliseconds consumed by reads so far."""
        return self._now_ms

    def timeout(self, delay: int, /) -> None:
        """Record the poll timeout the backend installs."""
        self._timeout_ms = delay

    def getch(self) -> int:
        """Return the next key to arrive within the timeout, else `curses` ERR.

        Once `reads` keys have been read, return the exit key.
        """
        if self._reads_left == 0:
            return ord("q")
        self._reads_left -= 1
        deadline = self._now_ms + self._timeout_ms
        if self._arrivals and self._arrivals[0] <= deadline:
            self._now_ms = self._arrivals.pop(0)
            return self._key
        self._now_ms = deadline
        return _CURSES_ERR


class ScriptedWindowStub:
    """Stub `curses.window` returning a fixed sequence of `getch` results."""

    def __init__(self, keys: list[int]) -> None:
        self._keys = list(keys)

    def timeout(self, delay: int, /) -> None:
        """Accept the poll timeout the backend installs and ignore it."""

    def getch(self) -> int:
        """Return the next scripted key, or `curses` ERR once exhausted."""
        return self._keys.pop(0) if self._keys else _CURSES_ERR


def _read_commands(backend: KeyboardInputBackend) -> list[Command]:
    """Read `backend` until it quits and return the commands it published."""
    commands: list[Command] = []
    asyncio.run(backend.read(lambda reading: commands.append(reading[0])))
    return commands


class TestCommandFromKey:
    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            pytest.param(ord("w"), (Command.ADVANCE, 50), id="w"),
            pytest.param(ord("s"), (Command.RETREAT, 50), id="s"),
            pytest.param(ord("a"), (Command.TURN_LEFT, 50), id="a"),
            pytest.param(ord("d"), (Command.TURN_RIGHT, 50), id="d"),
            pytest.param(
                curses.KEY_LEFT, (Command.LOOK_HORIZONTALLY, -45), id="arrow_left"
            ),
            pytest.param(
                curses.KEY_RIGHT, (Command.LOOK_HORIZONTALLY, 45), id="arrow_right"
            ),
            pytest.param(curses.KEY_UP, (Command.LOOK_VERTICALLY, 45), id="arrow_up"),
            pytest.param(
                curses.KEY_DOWN, (Command.LOOK_VERTICALLY, -45), id="arrow_down"
            ),
        ],
    )
    def test_translates_key_to_command(self, key: int, expected: DriveCommand) -> None:
        assert command_from_key(key) == expected

    def test_exit_key_quits(self) -> None:
        assert command_from_key(ord("q")) is None

    @pytest.mark.parametrize(
        "key",
        [pytest.param(_CURSES_ERR, id="no_key"), pytest.param(ord("z"), id="unbound")],
    )
    def test_reads_back_as_brake(self, key: int) -> None:
        assert command_from_key(key) == (Command.BRAKE, None)


class TestKeyboardInputBackend:
    @pytest.mark.parametrize(
        "repeat_delay_ms",
        [pytest.param(500, id="ubuntu_default"), pytest.param(200, id="shortened")],
    )
    def test_held_key_never_brakes_while_the_timeout_clears_the_repeat_delay(
        self, repeat_delay_ms: int
    ) -> None:
        window = HeldKeyWindowStub(ord("a"), repeat_delay_ms=repeat_delay_ms)

        commands = _read_commands(KeyboardInputBackend(window))

        assert Command.BRAKE not in commands

    def test_held_key_stutters_when_the_timeout_is_below_the_repeat_delay(
        self,
    ) -> None:
        """The pre-fix behavior, kept as the counter-example to the invariant."""
        window = HeldKeyWindowStub(ord("a"), repeat_delay_ms=500)

        commands = _read_commands(KeyboardInputBackend(window, poll_timeout_ms=50))

        assert commands.count(Command.BRAKE) > 1

    def test_release_brakes_within_the_poll_timeout(self) -> None:
        hold_ms = 1000
        window = HeldKeyWindowStub(ord("a"), hold_ms=hold_ms)
        braked_at_ms: list[int] = []

        def record_brake(reading: DriveCommand) -> None:
            if reading[0] is Command.BRAKE:
                braked_at_ms.append(window.elapsed_ms)

        asyncio.run(KeyboardInputBackend(window).read(record_brake))

        assert braked_at_ms[0] - hold_ms <= _KEYBOARD_POLL_TIMEOUT_MS

    @pytest.mark.asyncio
    async def test_publishes_each_reading_until_q(self) -> None:
        window = ScriptedWindowStub([ord("a"), ord("a"), ord("d"), ord("q")])
        published: list[DriveCommand] = []

        await KeyboardInputBackend(window).read(published.append)

        assert published == [
            (Command.TURN_LEFT, 50),
            (Command.TURN_LEFT, 50),
            (Command.TURN_RIGHT, 50),
        ]
