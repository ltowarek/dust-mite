from controller.command import Command
from controller.senders import InMemoryCommandSender


class TestInMemoryCommandSender:
    def test_starts_empty(self) -> None:
        sender = InMemoryCommandSender()
        assert sender.sent == []

    def test_records_sent_commands_in_order(self) -> None:
        sender = InMemoryCommandSender()

        sender.send(Command.ADVANCE, 50)
        sender.send(Command.BRAKE, None)

        assert sender.sent == [(Command.ADVANCE, 50), (Command.BRAKE, None)]
