from controller.command import Command
from controller.controller import control
from controller.senders import InMemoryCommandSender


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

    def test_does_not_resend_unchanged_command(self) -> None:
        input_backend = FakeInputBackend(
            [(Command.ADVANCE, 50), (Command.ADVANCE, 50), None]
        )
        sender = InMemoryCommandSender()

        control(input_backend, sender)

        assert sender.sent == [(Command.ADVANCE, 50)]

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
