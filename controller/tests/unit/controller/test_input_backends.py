import curses

import pytest

from controller.command import Command
from controller.controller import control
from controller.input_backends import (
    _KEYBOARD_POLL_TIMEOUT_MS,
    DualSenseInputBackend,
    KeyboardInputBackend,
)
from controller.senders import InMemoryCommandSender


class FakeDualSenseState:
    def __init__(  # noqa: PLR0913 - mirrors pydualsense's flat state fields
        self,
        *,
        ps: int = 0,
        dpad_up: int = 0,
        dpad_right: int = 0,
        dpad_down: int = 0,
        dpad_left: int = 0,
        lx: int = 0,
        rx: int = 0,
        ry: int = 0,
        r2: int = 0,
    ) -> None:
        self.ps = ps
        self.DpadUp = dpad_up
        self.DpadRight = dpad_right
        self.DpadDown = dpad_down
        self.DpadLeft = dpad_left
        self.LX = lx
        self.RX = rx
        self.RY = ry
        self.R2 = r2


class FakeDualSense:
    def __init__(self, state: FakeDualSenseState) -> None:
        self.state = state


class AutoExitDualSenseState:
    """Dpad-up held, with `ps` reading truthy after `exit_after` reads.

    `DualSenseInputBackend.poll` reads `.ps` exactly once per call, so this
    drives `control()` through exactly `exit_after` sent commands before the
    PS button "exit" condition trips.
    """

    def __init__(self, exit_after: int) -> None:
        self.DpadUp = 1
        self.DpadRight = 0
        self.DpadDown = 0
        self.DpadLeft = 0
        self.LX = 0
        self.RX = 0
        self.RY = 0
        self.R2 = 0
        self._exit_after = exit_after
        self._ps_reads = 0

    @property
    def ps(self) -> int:
        self._ps_reads += 1
        return int(self._ps_reads > self._exit_after)


class AutoExitDualSense:
    def __init__(self, state: AutoExitDualSenseState) -> None:
        self.state = state


class TestDualSenseInputBackend:
    def test_ps_button_returns_none(self) -> None:
        ds = FakeDualSense(FakeDualSenseState(ps=1))
        backend = DualSenseInputBackend(ds)
        assert backend.poll() is None

    @pytest.mark.parametrize(
        ("state_kwargs", "expected"),
        [
            pytest.param({}, (Command.BRAKE, None), id="no_input"),
            pytest.param({"dpad_up": 1}, (Command.ADVANCE, 50), id="dpad_up"),
            pytest.param({"dpad_right": 1}, (Command.TURN_RIGHT, 50), id="dpad_right"),
            pytest.param({"dpad_down": 1}, (Command.RETREAT, 50), id="dpad_down"),
            pytest.param({"dpad_left": 1}, (Command.TURN_LEFT, 50), id="dpad_left"),
            pytest.param(
                {"lx": 5}, (Command.BRAKE, None), id="left_stick_within_dead_zone"
            ),
            pytest.param(
                {"lx": -128}, (Command.TURN_LEFT, 100), id="left_stick_negative"
            ),
            pytest.param(
                {"lx": 127}, (Command.TURN_RIGHT, 100), id="left_stick_positive"
            ),
            pytest.param(
                {"rx": 127}, (Command.LOOK_HORIZONTALLY, 90), id="right_stick_x"
            ),
            pytest.param(
                {"ry": -128}, (Command.LOOK_VERTICALLY, 90), id="right_stick_y"
            ),
            pytest.param({"r2": 255}, (Command.ADVANCE, 100), id="r2"),
        ],
    )
    def test_translates_state_to_command(
        self, state_kwargs: dict[str, int], expected: tuple[Command, int | None]
    ) -> None:
        ds = FakeDualSense(FakeDualSenseState(**state_kwargs))
        backend = DualSenseInputBackend(ds)
        assert backend.poll() == expected

    def test_drives_the_control_loop(self) -> None:
        ds = AutoExitDualSense(AutoExitDualSenseState(exit_after=1))
        backend = DualSenseInputBackend(ds)
        sender = InMemoryCommandSender()

        control(backend, sender)

        assert sender.sent == [(Command.ADVANCE, 50)]


class FakeCursesWindow:
    def __init__(self, keys: list[int]) -> None:
        self._keys = iter(keys)
        self.timeout_ms: int | None = None

    def timeout(self, delay: int) -> None:
        self.timeout_ms = delay

    def getch(self) -> int:
        return next(self._keys, -1)


class TestKeyboardInputBackend:
    def test_sets_polling_timeout(self) -> None:
        window = FakeCursesWindow([])
        KeyboardInputBackend(window)
        assert window.timeout_ms == _KEYBOARD_POLL_TIMEOUT_MS

    def test_q_returns_none(self) -> None:
        backend = KeyboardInputBackend(FakeCursesWindow([ord("q")]))
        assert backend.poll() is None

    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            pytest.param(-1, (Command.BRAKE, None), id="no_key"),
            pytest.param(ord("w"), (Command.ADVANCE, 50), id="w"),
            pytest.param(ord("s"), (Command.RETREAT, 50), id="s"),
            pytest.param(ord("a"), (Command.TURN_LEFT, 50), id="a"),
            pytest.param(ord("d"), (Command.TURN_RIGHT, 50), id="d"),
            pytest.param(
                curses.KEY_LEFT, (Command.LOOK_HORIZONTALLY, -45), id="left_arrow"
            ),
            pytest.param(
                curses.KEY_RIGHT, (Command.LOOK_HORIZONTALLY, 45), id="right_arrow"
            ),
            pytest.param(curses.KEY_UP, (Command.LOOK_VERTICALLY, 45), id="up_arrow"),
            pytest.param(
                curses.KEY_DOWN, (Command.LOOK_VERTICALLY, -45), id="down_arrow"
            ),
            pytest.param(ord("z"), (Command.BRAKE, None), id="unrecognized_key"),
        ],
    )
    def test_translates_key_to_command(
        self, key: int, expected: tuple[Command, int | None]
    ) -> None:
        backend = KeyboardInputBackend(FakeCursesWindow([key]))
        assert backend.poll() == expected

    def test_drives_the_control_loop(self) -> None:
        window = FakeCursesWindow([ord("w"), ord("w"), ord("q")])
        backend = KeyboardInputBackend(window)
        sender = InMemoryCommandSender()

        control(backend, sender)

        assert sender.sent == [(Command.ADVANCE, 50)]
