"""controller module."""

import curses
import dataclasses
import logging
import os
from collections.abc import Mapping
from typing import Self

from .command import Command
from .curses_logging import curses_console_logging
from .input_backends import (
    DualSenseInputBackend,
    InputBackend,
    InputBackendName,
    KeyboardInputBackend,
)
from .observability import ObservabilitySettings, configure_observability
from .senders import CommandSender, DriveConnectionClosedError, WebSocketCommandSender

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


@dataclasses.dataclass(frozen=True)
class ControllerSettings:
    """The gamepad CLI's settings, read from the environment."""

    drive_uri: str
    input_backend: InputBackendName
    observability: ObservabilitySettings

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> Self:
        """Read the settings from `environ`; the app settings are required."""
        return cls(
            drive_uri=environ["STREAMER_DRIVE_URI"],
            input_backend=InputBackendName(environ["CONTROLLER_INPUT_BACKEND"]),
            observability=ObservabilitySettings.from_env(environ),
        )


def _configure_console_logging() -> logging.Handler:
    """Attach a plain stream handler for console output and return it."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(logging.BASIC_FORMAT))
    logging.getLogger().addHandler(handler)
    return handler


def control(input_backend: InputBackend, sender: CommandSender) -> None:
    """Read input in a loop and send commands to the car.

    Every command except a repeated BRAKE is sent on each poll, so a held
    command keeps the car's drive-command watchdog from braking.
    """
    last_command = Command.BRAKE

    while True:
        result = input_backend.poll()
        if result is None:
            break
        command, value = result

        if command != Command.BRAKE or last_command != Command.BRAKE:
            logger.debug("Sending command with value: %s - %s", command.name, value)
            sender.send(command, value)
        last_command = command


def main() -> None:
    """Run the main entry point."""
    settings = ControllerSettings.from_env(os.environ)
    configure_observability("dust-mite-controller", settings.observability)
    console_handler = _configure_console_logging()

    try:
        with WebSocketCommandSender(settings.drive_uri) as sender:
            if settings.input_backend is InputBackendName.KEYBOARD:

                def run(window: curses.window) -> None:
                    with curses_console_logging(window, console_handler):
                        control(KeyboardInputBackend(window), sender)

                curses.wrapper(run)
            else:
                with DualSenseInputBackend() as backend:
                    control(backend, sender)
    except DriveConnectionClosedError as e:
        message = f"The streamer closed the drive connection: {e}"
        raise SystemExit(message) from None


if __name__ == "__main__":
    main()
