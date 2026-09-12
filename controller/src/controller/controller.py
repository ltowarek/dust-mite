"""controller module."""

import curses
import logging
import os

from .command import Command
from .curses_logging import curses_console_logging
from .input_backends import (
    DualSenseInputBackend,
    InputBackend,
    InputBackendName,
    KeyboardInputBackend,
)
from .logging import configure_logging
from .senders import CommandSender, WebSocketCommandSender
from .tracing import configure_tracing

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def _configure_console_logging() -> logging.Handler:
    """Attach a plain stream handler for console output and return it."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(logging.BASIC_FORMAT))
    logging.getLogger().addHandler(handler)
    return handler


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
    console_handler = _configure_console_logging()
    controller_client_uri = os.environ["CONTROLLER_CLIENT_URI"]
    input_backend_name = InputBackendName(os.environ["CONTROLLER_INPUT_BACKEND"])

    with WebSocketCommandSender(controller_client_uri) as sender:
        if input_backend_name is InputBackendName.KEYBOARD:

            def run(window: curses.window) -> None:
                with curses_console_logging(window, console_handler):
                    control(KeyboardInputBackend(window), sender)

            curses.wrapper(run)
        else:
            with DualSenseInputBackend() as backend:
                control(backend, sender)


if __name__ == "__main__":
    main()
