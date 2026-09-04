# pexpect.spawn is generic only in its type stubs (pexpect-stubs), not at
# runtime, so `pexpect.spawn[str]` below would raise TypeError if evaluated
# eagerly. Deferring annotation evaluation keeps it string-only, read by
# mypy but never executed.
from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pexpect
import pytest

from controller.command import Command

if TYPE_CHECKING:
    from collections.abc import Generator

_WAIT_TIMEOUT_S = 5

# Drives KeyboardInputBackend directly against a real curses session,
# printing each poll() result - no websocket/CommandSender involved, since
# that path is already covered by test_controller_websocket.py and the
# fast unit tests in test_controller.py cover control()'s dedup/exit logic
# against a fake backend. This isolates exactly the thing that needs a real
# terminal to verify: does curses actually translate a real keypress the
# way _KEYBOARD_BINDINGS says it should.
_POLL_SCRIPT = """\
import curses

from controller.input_backends import KeyboardInputBackend


def main(window):
    backend = KeyboardInputBackend(window)
    while True:
        result = backend.poll()
        if result is None:
            print("RESULT None None", flush=True)
        else:
            command, value = result
            print(f"RESULT {command.value} {value}", flush=True)


curses.wrapper(main)
"""


@pytest.fixture
def keyboard_backend_process() -> Generator[pexpect.spawn[str], None, None]:
    env = {
        **os.environ,
        # Pinned rather than inherited: CI runners often leave TERM unset
        # or set to "dumb", and curses.initscr() needs a real terminfo
        # entry to succeed.
        "TERM": "xterm",
    }
    child = pexpect.spawn(
        sys.executable, ["-c", _POLL_SCRIPT], env=env, timeout=_WAIT_TIMEOUT_S
    )
    try:
        yield child
    finally:
        child.close(force=True)


@pytest.mark.parametrize(
    ("key", "expected_command", "expected_value"),
    [
        pytest.param("w", Command.ADVANCE, 50, id="w"),
        pytest.param("s", Command.RETREAT, 50, id="s"),
        pytest.param("a", Command.TURN_LEFT, 50, id="a"),
        pytest.param("d", Command.TURN_RIGHT, 50, id="d"),
    ],
)
def test_translates_key_to_command(
    keyboard_backend_process: pexpect.spawn[str],
    key: str,
    expected_command: Command,
    expected_value: int,
) -> None:
    keyboard_backend_process.send(key)
    keyboard_backend_process.expect(f"RESULT {expected_command.value} {expected_value}")


def test_q_returns_none(keyboard_backend_process: pexpect.spawn[str]) -> None:
    keyboard_backend_process.send("q")
    keyboard_backend_process.expect("RESULT None None")
