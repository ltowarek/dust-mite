import curses

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

    def test_no_input_returns_brake(self) -> None:
        ds = FakeDualSense(FakeDualSenseState())
        backend = DualSenseInputBackend(ds)
        assert backend.poll() == (Command.BRAKE, None)

    def test_dpad_up_returns_advance(self) -> None:
        ds = FakeDualSense(FakeDualSenseState(dpad_up=1))
        backend = DualSenseInputBackend(ds)
        assert backend.poll() == (Command.ADVANCE, 50)

    def test_dpad_right_returns_turn_right(self) -> None:
        ds = FakeDualSense(FakeDualSenseState(dpad_right=1))
        backend = DualSenseInputBackend(ds)
        assert backend.poll() == (Command.TURN_RIGHT, 50)

    def test_dpad_down_returns_retreat(self) -> None:
        ds = FakeDualSense(FakeDualSenseState(dpad_down=1))
        backend = DualSenseInputBackend(ds)
        assert backend.poll() == (Command.RETREAT, 50)

    def test_dpad_left_returns_turn_left(self) -> None:
        ds = FakeDualSense(FakeDualSenseState(dpad_left=1))
        backend = DualSenseInputBackend(ds)
        assert backend.poll() == (Command.TURN_LEFT, 50)

    def test_left_stick_within_dead_zone_is_ignored(self) -> None:
        ds = FakeDualSense(FakeDualSenseState(lx=5))
        backend = DualSenseInputBackend(ds)
        assert backend.poll() == (Command.BRAKE, None)

    def test_left_stick_negative_returns_turn_left(self) -> None:
        ds = FakeDualSense(FakeDualSenseState(lx=-128))
        backend = DualSenseInputBackend(ds)
        assert backend.poll() == (Command.TURN_LEFT, 100)

    def test_left_stick_positive_returns_turn_right(self) -> None:
        ds = FakeDualSense(FakeDualSenseState(lx=127))
        backend = DualSenseInputBackend(ds)
        assert backend.poll() == (Command.TURN_RIGHT, 100)

    def test_right_stick_x_returns_look_horizontally(self) -> None:
        ds = FakeDualSense(FakeDualSenseState(rx=127))
        backend = DualSenseInputBackend(ds)
        assert backend.poll() == (Command.LOOK_HORIZONTALLY, 90)

    def test_right_stick_y_returns_look_vertically(self) -> None:
        ds = FakeDualSense(FakeDualSenseState(ry=-128))
        backend = DualSenseInputBackend(ds)
        assert backend.poll() == (Command.LOOK_VERTICALLY, 90)

    def test_r2_returns_advance(self) -> None:
        ds = FakeDualSense(FakeDualSenseState(r2=255))
        backend = DualSenseInputBackend(ds)
        assert backend.poll() == (Command.ADVANCE, 100)

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

    def test_no_key_returns_brake(self) -> None:
        backend = KeyboardInputBackend(FakeCursesWindow([-1]))
        assert backend.poll() == (Command.BRAKE, None)

    def test_w_returns_advance(self) -> None:
        backend = KeyboardInputBackend(FakeCursesWindow([ord("w")]))
        assert backend.poll() == (Command.ADVANCE, 50)

    def test_s_returns_retreat(self) -> None:
        backend = KeyboardInputBackend(FakeCursesWindow([ord("s")]))
        assert backend.poll() == (Command.RETREAT, 50)

    def test_a_returns_turn_left(self) -> None:
        backend = KeyboardInputBackend(FakeCursesWindow([ord("a")]))
        assert backend.poll() == (Command.TURN_LEFT, 50)

    def test_d_returns_turn_right(self) -> None:
        backend = KeyboardInputBackend(FakeCursesWindow([ord("d")]))
        assert backend.poll() == (Command.TURN_RIGHT, 50)

    def test_left_arrow_returns_look_horizontally_negative(self) -> None:
        backend = KeyboardInputBackend(FakeCursesWindow([curses.KEY_LEFT]))
        assert backend.poll() == (Command.LOOK_HORIZONTALLY, -45)

    def test_right_arrow_returns_look_horizontally_positive(self) -> None:
        backend = KeyboardInputBackend(FakeCursesWindow([curses.KEY_RIGHT]))
        assert backend.poll() == (Command.LOOK_HORIZONTALLY, 45)

    def test_up_arrow_returns_look_vertically_positive(self) -> None:
        backend = KeyboardInputBackend(FakeCursesWindow([curses.KEY_UP]))
        assert backend.poll() == (Command.LOOK_VERTICALLY, 45)

    def test_down_arrow_returns_look_vertically_negative(self) -> None:
        backend = KeyboardInputBackend(FakeCursesWindow([curses.KEY_DOWN]))
        assert backend.poll() == (Command.LOOK_VERTICALLY, -45)

    def test_q_returns_none(self) -> None:
        backend = KeyboardInputBackend(FakeCursesWindow([ord("q")]))
        assert backend.poll() is None

    def test_unrecognized_key_returns_brake(self) -> None:
        backend = KeyboardInputBackend(FakeCursesWindow([ord("z")]))
        assert backend.poll() == (Command.BRAKE, None)

    def test_drives_the_control_loop(self) -> None:
        window = FakeCursesWindow([ord("w"), ord("w"), ord("q")])
        backend = KeyboardInputBackend(window)
        sender = InMemoryCommandSender()

        control(backend, sender)

        assert sender.sent == [(Command.ADVANCE, 50)]
