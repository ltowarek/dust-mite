"""controller module."""

import asyncio
import curses
import dataclasses
import logging
import os
from collections.abc import Callable, Mapping
from typing import NoReturn, Self

from websockets.asyncio.client import ClientConnection

from .autorepeat import Event, Parked, SendState, Tick, resend_due, transition
from .command import DriveCommand
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


async def autorepeat(
    readings: asyncio.Queue[DriveCommand], publish: Callable[[DriveCommand], None]
) -> NoReturn:
    """Publish the Drive commands `transition` returns for each reading and tick."""
    loop = asyncio.get_running_loop()
    state: SendState = Parked()
    while True:
        event: Event
        try:
            async with asyncio.timeout_at(resend_due(state)):
                event = await readings.get()
        except TimeoutError:
            event = Tick()
        state, commands = transition(state, event, loop.time())
        for command, value in commands:
            logger.debug("Sending command with value: %s - %s", command.name, value)
            publish((command, value))


async def drive(input_backend: InputBackend, drive_uri: str) -> None:
    """Drive the car through the streamer at `drive_uri` until the input ends.

    Raises `DriveConnectionClosedError` if the streamer closes deliberately.
    """
    readings: asyncio.Queue[DriveCommand] = asyncio.Queue()
    commands: Broadcast[DriveCommand] = Broadcast()
    async with asyncio.TaskGroup() as tasks:
        reader = tasks.create_task(input_backend.read(readings.put_nowait))
        sender = tasks.create_task(autorepeat(readings, commands.publish))
        watcher = tasks.create_task(
            _send_until_closed_deliberately(drive_uri, commands)
        )
        await asyncio.wait([reader, watcher], return_when=asyncio.FIRST_COMPLETED)
        reader.cancel()
        sender.cancel()
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

            def run_keyboard(window: curses.window) -> None:
                write_queued_logs = queued_log_writer(
                    records, window, console_handler.formatter
                )
                backend = KeyboardInputBackend(window, write_queued_logs)
                asyncio.run(drive(backend, settings.drive_uri))

            with queued_console_logging(console_handler) as records:
                curses.wrapper(run_keyboard)
        else:

            async def run_dualsense() -> None:
                async with DualSenseInputBackend() as backend:
                    await drive(backend, settings.drive_uri)

            asyncio.run(run_dualsense())
    except DriveConnectionClosedError as e:
        message = f"The streamer closed the drive connection: {e}"
        raise SystemExit(message) from None


if __name__ == "__main__":
    main()
