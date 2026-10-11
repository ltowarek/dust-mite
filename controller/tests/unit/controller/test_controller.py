import logging

from controller.command import Command
from controller.controller import _configure_console_logging, control
from controller.senders import InMemoryCommandSender


class TestConfigureConsoleLogging:
    def test_attaches_a_stream_handler_to_the_root_logger(
        self, root_logger: logging.Logger
    ) -> None:
        handler = _configure_console_logging()

        assert handler in root_logger.handlers
        assert isinstance(handler, logging.StreamHandler)


class FakeInputBackend:
    def __init__(self, results: list[tuple[Command, int | None] | None]) -> None:
        self._results = iter(results)

    def poll(self) -> tuple[Command, int | None] | None:
        return next(self._results)


class TestControl:
    def test_exits_immediately_when_backend_returns_none(self) -> None:
        input_backend = FakeInputBackend([None])
        sender = InMemoryCommandSender()

        control(input_backend, sender)

        assert sender.sent == []

    def test_sends_first_command(self) -> None:
        input_backend = FakeInputBackend([(Command.ADVANCE, 50), None])
        sender = InMemoryCommandSender()

        control(input_backend, sender)

        assert sender.sent == [(Command.ADVANCE, 50)]

    def test_resends_an_unchanged_non_brake_command(self) -> None:
        """Keeps the car's drive-command watchdog satisfied while a command is held."""
        input_backend = FakeInputBackend(
            [(Command.ADVANCE, 50), (Command.ADVANCE, 50), None]
        )
        sender = InMemoryCommandSender()

        control(input_backend, sender)

        assert sender.sent == [(Command.ADVANCE, 50), (Command.ADVANCE, 50)]

    def test_does_not_resend_repeated_brake(self) -> None:
        input_backend = FakeInputBackend(
            [(Command.ADVANCE, 50), (Command.BRAKE, None), (Command.BRAKE, None), None]
        )
        sender = InMemoryCommandSender()

        control(input_backend, sender)

        assert sender.sent == [(Command.ADVANCE, 50), (Command.BRAKE, None)]

    def test_sends_again_when_value_changes(self) -> None:
        input_backend = FakeInputBackend(
            [(Command.TURN_LEFT, 30), (Command.TURN_LEFT, 60), None]
        )
        sender = InMemoryCommandSender()

        control(input_backend, sender)

        assert sender.sent == [(Command.TURN_LEFT, 30), (Command.TURN_LEFT, 60)]

    def test_sends_again_when_command_changes(self) -> None:
        input_backend = FakeInputBackend(
            [(Command.ADVANCE, 50), (Command.BRAKE, None), None]
        )
        sender = InMemoryCommandSender()

        control(input_backend, sender)

        assert sender.sent == [(Command.ADVANCE, 50), (Command.BRAKE, None)]
