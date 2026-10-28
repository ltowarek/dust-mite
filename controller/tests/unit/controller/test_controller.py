import logging

import pytest

from controller.command import Command, DriveCommand
from controller.controller import (
    ControllerSettings,
    _configure_console_logging,
    control,
)
from controller.input_backends import InputBackendName

from .test_doubles import CommandSenderSpy


class TestConfigureConsoleLogging:
    def test_attaches_a_stream_handler_to_the_root_logger(
        self, root_logger: logging.Logger
    ) -> None:
        handler = _configure_console_logging()

        assert handler in root_logger.handlers
        assert isinstance(handler, logging.StreamHandler)


class InputBackendStub:
    def __init__(self, results: list[DriveCommand | None]) -> None:
        self._results = iter(results)

    def poll(self) -> DriveCommand | None:
        return next(self._results)


class TestControl:
    def test_exits_immediately_when_backend_returns_none(self) -> None:
        input_backend = InputBackendStub([None])
        sender = CommandSenderSpy()

        control(input_backend, sender)

        assert sender.sent == []

    def test_sends_first_command(self) -> None:
        input_backend = InputBackendStub([(Command.ADVANCE, 50), None])
        sender = CommandSenderSpy()

        control(input_backend, sender)

        assert sender.sent == [(Command.ADVANCE, 50)]

    def test_resends_an_unchanged_non_brake_command(self) -> None:
        """Keeps the car's drive-command watchdog satisfied while a command is held."""
        input_backend = InputBackendStub(
            [(Command.ADVANCE, 50), (Command.ADVANCE, 50), None]
        )
        sender = CommandSenderSpy()

        control(input_backend, sender)

        assert sender.sent == [(Command.ADVANCE, 50), (Command.ADVANCE, 50)]

    def test_does_not_resend_repeated_brake(self) -> None:
        input_backend = InputBackendStub(
            [(Command.ADVANCE, 50), (Command.BRAKE, None), (Command.BRAKE, None), None]
        )
        sender = CommandSenderSpy()

        control(input_backend, sender)

        assert sender.sent == [(Command.ADVANCE, 50), (Command.BRAKE, None)]

    def test_sends_again_when_value_changes(self) -> None:
        input_backend = InputBackendStub(
            [(Command.TURN_LEFT, 30), (Command.TURN_LEFT, 60), None]
        )
        sender = CommandSenderSpy()

        control(input_backend, sender)

        assert sender.sent == [(Command.TURN_LEFT, 30), (Command.TURN_LEFT, 60)]

    def test_sends_again_when_command_changes(self) -> None:
        input_backend = InputBackendStub(
            [(Command.ADVANCE, 50), (Command.BRAKE, None), None]
        )
        sender = CommandSenderSpy()

        control(input_backend, sender)

        assert sender.sent == [(Command.ADVANCE, 50), (Command.BRAKE, None)]


_CONTROLLER_ENV = {
    "STREAMER_DRIVE_URI": "ws://streamer.invalid/drive",
    "CONTROLLER_INPUT_BACKEND": "keyboard",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector.invalid",
}


class TestControllerSettingsFromEnv:
    def test_reads_the_streamer_drive_uri(self) -> None:
        settings = ControllerSettings.from_env(_CONTROLLER_ENV)

        assert settings.drive_uri == "ws://streamer.invalid/drive"

    def test_reads_the_input_backend(self) -> None:
        settings = ControllerSettings.from_env(_CONTROLLER_ENV)

        assert settings.input_backend is InputBackendName.KEYBOARD

    def test_reads_the_observability_settings(self) -> None:
        settings = ControllerSettings.from_env(_CONTROLLER_ENV)

        assert settings.observability.traces_endpoint == (
            "http://collector.invalid/v1/traces"
        )

    @pytest.mark.parametrize(
        "variable", ["STREAMER_DRIVE_URI", "CONTROLLER_INPUT_BACKEND"]
    )
    def test_requires_each_app_variable(self, variable: str) -> None:
        environ = {k: v for k, v in _CONTROLLER_ENV.items() if k != variable}

        with pytest.raises(KeyError, match=variable):
            ControllerSettings.from_env(environ)

    def test_rejects_an_unknown_input_backend(self) -> None:
        environ = {**_CONTROLLER_ENV, "CONTROLLER_INPUT_BACKEND": "joystick"}

        with pytest.raises(ValueError, match="joystick"):
            ControllerSettings.from_env(environ)
