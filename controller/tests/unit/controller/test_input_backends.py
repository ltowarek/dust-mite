import curses

import pytest
from pydualsense import pydualsense
from pydualsense.pydualsense import DSState

from controller import input_backends
from controller.command import Command
from controller.controller import control
from controller.input_backends import (
    _KEYBOARD_POLL_TIMEOUT_MS,
    DualSenseInputBackend,
    KeyboardInputBackend,
)
from controller.senders import InMemoryCommandSender

# `curses.getch` returns -1 (ERR) when the poll timeout lapses with no key.
_CURSES_ERR = -1


def _dualsense(**state_overrides: bool | int) -> pydualsense:
    """Build a real, hardware-free `pydualsense` with `.state` fields set."""
    ds = pydualsense()
    ds.state = DSState()
    # DSState()'s raw LX/RX/RY/LY default (128) is an unpopulated
    # placeholder, not a real reading: `readInput()` normalizes a real
    # report to `raw_byte - 128`, so 0 is what an at-rest stick reads as.
    ds.state.LX = 0
    ds.state.RX = 0
    ds.state.RY = 0
    ds.state.LY = 0
    for name, value in state_overrides.items():
        setattr(ds.state, name, value)
    return ds


# DSState is untyped (Any), and mypy disallows subclassing Any.
class AutoExitDSState(DSState):  # type: ignore[misc]
    """Dpad-up held, with `.ps` reading truthy after `exit_after` reads.

    `DualSenseInputBackend.poll` reads `.ps` exactly once per call, so this
    drives `control()` through exactly `exit_after` sent commands before the
    PS button "exit" condition trips.
    """

    def __init__(self, exit_after: int) -> None:
        super().__init__()
        self.DpadUp = True
        self._exit_after = exit_after
        self._ps_reads = 0

    @property
    def ps(self) -> bool:
        self._ps_reads += 1
        return self._ps_reads > self._exit_after

    @ps.setter
    def ps(self, value: bool) -> None:
        pass


class TestDualSenseInputBackend:
    def test_ps_button_returns_none(self) -> None:
        backend = DualSenseInputBackend(_dualsense(ps=True))
        assert backend.poll() is None

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
        expected: tuple[Command, int | None],
    ) -> None:
        backend = DualSenseInputBackend(_dualsense(**state_overrides))
        assert backend.poll() == expected

    def test_drives_the_control_loop(self) -> None:
        ds = pydualsense()
        ds.state = AutoExitDSState(exit_after=1)
        backend = DualSenseInputBackend(ds)
        sender = InMemoryCommandSender()

        control(backend, sender)

        assert sender.sent == [(Command.ADVANCE, 50)]


class HeldKeyWindow:
    """Fake `curses.window` replaying one key held down under auto-repeat.

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
    ) -> None:
        self._arrivals = self._arrival_times(
            repeat_delay_ms, repeat_interval_ms, hold_ms
        )
        self._key = key
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
        """Return the next key to arrive within the timeout, else `curses` ERR."""
        deadline = self._now_ms + self._timeout_ms
        if self._arrivals and self._arrivals[0] <= deadline:
            self._now_ms = self._arrivals.pop(0)
            return self._key
        self._now_ms = deadline
        return _CURSES_ERR


class ScriptedWindow:
    """Fake `curses.window` returning a fixed sequence of `getch` results."""

    def __init__(self, keys: list[int]) -> None:
        self._keys = list(keys)

    def timeout(self, delay: int, /) -> None:
        """Accept the poll timeout the backend installs and ignore it."""

    def getch(self) -> int:
        """Return the next scripted key, or `curses` ERR once exhausted."""
        return self._keys.pop(0) if self._keys else _CURSES_ERR


def _drive(backend: KeyboardInputBackend, polls: int) -> list[Command]:
    """Poll `backend` `polls` times and return the commands it emitted."""
    commands: list[Command] = []
    for _ in range(polls):
        result = backend.poll()
        assert result is not None
        commands.append(result[0])
    return commands


class TestKeyboardInputBackend:
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
    def test_translates_key_to_command(
        self, key: int, expected: tuple[Command, int | None]
    ) -> None:
        backend = KeyboardInputBackend(ScriptedWindow([key]))
        assert backend.poll() == expected

    def test_exit_key_returns_none(self) -> None:
        backend = KeyboardInputBackend(ScriptedWindow([ord("q")]))
        assert backend.poll() is None

    @pytest.mark.parametrize(
        "key",
        [pytest.param(_CURSES_ERR, id="no_key"), pytest.param(ord("z"), id="unbound")],
    )
    def test_reads_back_as_brake(self, key: int) -> None:
        backend = KeyboardInputBackend(ScriptedWindow([key]))
        assert backend.poll() == (Command.BRAKE, None)

    @pytest.mark.parametrize(
        "repeat_delay_ms",
        [pytest.param(500, id="ubuntu_default"), pytest.param(200, id="shortened")],
    )
    def test_held_key_never_brakes_while_the_timeout_clears_the_repeat_delay(
        self, repeat_delay_ms: int
    ) -> None:
        window = HeldKeyWindow(ord("a"), repeat_delay_ms=repeat_delay_ms)

        commands = _drive(KeyboardInputBackend(window), polls=20)

        assert Command.BRAKE not in commands

    def test_held_key_stutters_when_the_timeout_is_below_the_repeat_delay(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The pre-fix behavior, kept as the counter-example to the invariant."""
        monkeypatch.setattr(input_backends, "_KEYBOARD_POLL_TIMEOUT_MS", 50)
        window = HeldKeyWindow(ord("a"), repeat_delay_ms=500)

        commands = _drive(KeyboardInputBackend(window), polls=20)

        assert commands.count(Command.BRAKE) > 1

    def test_release_brakes_within_the_poll_timeout(self) -> None:
        hold_ms = 1000
        window = HeldKeyWindow(ord("a"), hold_ms=hold_ms)
        backend = KeyboardInputBackend(window)

        while True:
            result = backend.poll()
            assert result is not None
            if result[0] is Command.BRAKE:
                break

        assert window.elapsed_ms - hold_ms <= _KEYBOARD_POLL_TIMEOUT_MS

    def test_drives_the_control_loop(self) -> None:
        window = ScriptedWindow([ord("a"), ord("a"), ord("d"), ord("q")])
        sender = InMemoryCommandSender()

        control(KeyboardInputBackend(window), sender)

        assert sender.sent == [(Command.TURN_LEFT, 50), (Command.TURN_RIGHT, 50)]
