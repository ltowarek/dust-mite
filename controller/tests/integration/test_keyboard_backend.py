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

    from .conftest import LocalServer

_WAIT_TIMEOUT_S = 5


@pytest.fixture
def keyboard_backend_process(
    local_server: LocalServer,
) -> Generator[pexpect.spawn[str], None, None]:
    env = {
        **os.environ,
        # Pinned rather than inherited: CI runners often leave TERM unset
        # or set to "dumb", and curses.initscr() needs a real terminfo
        # entry to succeed.
        "TERM": "xterm",
        "CONTROLLER_INPUT_BACKEND": "keyboard",
        "CONTROLLER_CLIENT_URI": local_server.uri,
        "OTEL_EXPORTER_OTLP_ENDPOINT": "",
    }
    child = pexpect.spawn(
        sys.executable,
        ["-m", "controller.controller"],
        env=env,
        timeout=_WAIT_TIMEOUT_S,
    )
    try:
        yield child
    finally:
        child.close(force=True)


def test_keyboard_backend_sends_command_over_the_wire(
    local_server: LocalServer,
    keyboard_backend_process: pexpect.spawn[str],
) -> None:
    sent_value = 50
    keyboard_backend_process.send("w")
    assert local_server.message_received.wait(timeout=_WAIT_TIMEOUT_S)
    keyboard_backend_process.send("q")
    keyboard_backend_process.expect(pexpect.EOF)
    # expect(EOF) only confirms the child's output stream ended; close()
    # reaps the process so exitstatus is actually populated.
    keyboard_backend_process.close()

    assert keyboard_backend_process.exitstatus == 0
    assert local_server.received[0]["command"] == Command.ADVANCE.value
    assert local_server.received[0]["value"] == sent_value
