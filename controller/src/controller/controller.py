"""controller module."""

import logging
import os

from .command import Command
from .input_backends import InputBackend, InputBackendName, create_input_backend
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
    input_backend_name = InputBackendName(os.environ["CONTROLLER_INPUT_BACKEND"])

    with (
        WebSocketCommandSender(controller_client_uri) as sender,
        create_input_backend(input_backend_name) as backend,
    ):
        control(backend, sender)


if __name__ == "__main__":
    main()
