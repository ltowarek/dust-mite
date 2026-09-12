import pytest

from controller import senders
from controller.command import Command
from controller.senders import InMemoryCommandSender, WebSocketCommandSender


class _RecordingConnection:
    """Stand-in for a `websockets` client connection that captures payloads."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, payload: str, /) -> None:
        """Capture `payload` instead of writing it to a socket."""
        self.sent.append(payload)

    def close(self) -> None:
        """Accept the sender's teardown call."""


class TestInMemoryCommandSender:
    def test_starts_empty(self) -> None:
        sender = InMemoryCommandSender()
        assert sender.sent == []

    def test_records_sent_commands_in_order(self) -> None:
        sender = InMemoryCommandSender()

        sender.send(Command.ADVANCE, 50)
        sender.send(Command.BRAKE, None)

        assert sender.sent == [(Command.ADVANCE, 50), (Command.BRAKE, None)]


class TestWebSocketCommandSender:
    def test_records_a_metric_for_every_command_sent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: list[Command] = []
        monkeypatch.setattr(senders, "record_command_sent", recorded.append)
        sender = WebSocketCommandSender("ws://example.invalid")
        sender._ws_conn = _RecordingConnection()  # noqa: SLF001

        sender.send(Command.TURN_LEFT, 50)
        sender.send(Command.BRAKE, None)

        assert recorded == [Command.TURN_LEFT, Command.BRAKE]
