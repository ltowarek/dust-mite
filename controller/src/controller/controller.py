"""controller module."""

import asyncio
import curses
import dataclasses
import logging
import os
from collections.abc import Callable, Mapping
from typing import Self

from websockets.asyncio.client import ClientConnection

from .command import Command, DriveCommand
from .curses_logging import queued_console_logging, queued_log_writer
from .input_backends import (
    DualSenseInputBackend,
    InputBackend,
    InputBackendName,
    KeyboardInputBackend,
)
from .observability import ObservabilitySettings, configure_observability
from .outbox import Broadcast
from .reconnecting_connection import send_until_lost, stay_connected
from .senders import send_command

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class DriveConnectionClosedError(Exception):
    """The streamer closed the drive connection deliberately, with the reason given."""


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


async def control(
    input_backend: InputBackend,
    publish: Callable[[DriveCommand], None],
    between_polls: Callable[[], None] = lambda: None,
) -> None:
    """Read input in a loop and publish Drive commands.

    Every command except a repeated BRAKE is published on each poll, so a
    held command keeps the car's drive-command watchdog from braking.
    `between_polls` runs before each poll, which runs in a worker thread.
    """
    last_command = Command.BRAKE

    while True:
        between_polls()
        result = await asyncio.to_thread(input_backend.poll)
        if result is None:
            break
        command, value = result

        if command != Command.BRAKE or last_command != Command.BRAKE:
            logger.debug("Sending command with value: %s - %s", command.name, value)
            publish(result)
        last_command = command


async def drive(
    input_backend: InputBackend,
    drive_uri: str,
    between_polls: Callable[[], None] = lambda: None,
) -> None:
    """Drive the car through the streamer at `drive_uri` until the input ends.

    Raises `DriveConnectionClosedError` if the streamer closes deliberately.
    """
    commands: Broadcast[DriveCommand] = Broadcast()
    async with asyncio.TaskGroup() as tasks:
        reader = tasks.create_task(
            control(input_backend, commands.publish, between_polls)
        )
        watcher = tasks.create_task(
            _send_until_closed_deliberately(drive_uri, commands)
        )
        await asyncio.wait([reader, watcher], return_when=asyncio.FIRST_COMPLETED)
        reader.cancel()
        watcher.cancel()
    if not watcher.cancelled():
        raise watcher.result()


async def _send_until_closed_deliberately(
    uri: str, commands: Broadcast[DriveCommand]
) -> DriveConnectionClosedError:
    async def send_until_refused(connection: ClientConnection) -> None:
        reason = await send_until_lost(uri, connection, send_command, commands)
        if reason is not None:
            raise DriveConnectionClosedError(reason)

    try:
        await stay_connected(uri, send_until_refused)
    except DriveConnectionClosedError as closed:
        return closed


def main() -> None:
    """Run the main entry point."""
    settings = ControllerSettings.from_env(os.environ)
    configure_observability("dust-mite-controller", settings.observability)
    console_handler = _configure_console_logging()

    try:
        if settings.input_backend is InputBackendName.KEYBOARD:

            def run(window: curses.window) -> None:
                write_queued_logs = queued_log_writer(
                    records, window, console_handler.formatter
                )
                asyncio.run(
                    drive(
                        KeyboardInputBackend(window),
                        settings.drive_uri,
                        write_queued_logs,
                    )
                )

            with queued_console_logging(console_handler) as records:
                curses.wrapper(run)
        else:
            with DualSenseInputBackend() as backend:
                asyncio.run(drive(backend, settings.drive_uri))
    except DriveConnectionClosedError as e:
        message = f"The streamer closed the drive connection: {e}"
        raise SystemExit(message) from None


if __name__ == "__main__":
    main()
