"""controller module."""

import curses
import logging
import os

import websockets.sync.client
from pydualsense import pydualsense

from .command import Command
from .input_backends import (
    DualSenseInputBackend,
    InputBackend,
    InputBackendName,
    KeyboardInputBackend,
)
from .logging import configure_logging
from .senders import CommandSender, WebSocketCommandSender
from .tracing import configure_tracing

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def control(input_backend: InputBackend, sender: CommandSender) -> None:
    """Read input in a loop and send commands to the car."""
    last_command = Command.BRAKE
    last_value: int | None = None

    while True:
        result = input_backend.poll()
        if result is None:
            break
        command, value = result

        if (command != last_command) or (value != last_value):
            logger.debug("Sending new command with value: %s - %s", command.name, value)
            sender.send(command, value)
            last_command = command
            last_value = value


def main() -> None:
    """Run the main entry point."""
    configure_tracing("dust-mite-controller")
    configure_logging("dust-mite-controller")
    controller_client_uri = os.environ["CONTROLLER_CLIENT_URI"]
    input_backend_name = InputBackendName(
        os.environ.get("CONTROLLER_INPUT_BACKEND", InputBackendName.DUALSENSE)
    )

    ws_conn = websockets.sync.client.connect(controller_client_uri)
    sender = WebSocketCommandSender(ws_conn)

    if input_backend_name is InputBackendName.KEYBOARD:
        curses.wrapper(lambda window: control(KeyboardInputBackend(window), sender))
    else:
        ds = pydualsense()
        ds.init()
        control(DualSenseInputBackend(ds), sender)
        ds.close()

    ws_conn.close()


if __name__ == "__main__":
    main()
