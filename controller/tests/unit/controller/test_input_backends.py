import curses

import pytest
from pydualsense import pydualsense
from pydualsense.pydualsense import DSState

from controller.command import Command
from controller.controller import control
from controller.input_backends import (
    _KEYBOARD_POLL_TIMEOUT_MS,
    DualSenseInputBackend,
    KeyboardInputBackend,
)
from controller.senders import InMemoryCommandSender


def _dualsense(**state_overrides: bool | int) -> pydualsense:
    """Build a real, hardware-free `pydualsense` with `.state` fields set.

    `pydualsense()` itself never touches hardware (only `.init()` does), and
    `DSState` is a plain object, so this uses the library's own classes
    instead of a hand-rolled stand-in for its state shape.
    """
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


class FakeCursesWindow:
    def __init__(self, keys: list[int]) -> None:
        self._keys = iter(keys)
        self.timeout_ms: int | None = None

    def timeout(self, delay: int) -> None:
        self.timeout_ms = delay

    def getch(self) -> int:
        return next(self._keys, -1)

    def keypad(self, flag: bool) -> None:  # noqa: FBT001 - matches curses' C API
        pass


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
