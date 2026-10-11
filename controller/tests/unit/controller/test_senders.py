import pytest
import websockets.exceptions
from websockets.frames import Close, CloseCode

from controller import senders
from controller.command import Command
from controller.senders import (
    DriveConnectionClosedError,
    InMemoryCommandSender,
    WebSocketCommandSender,
)

_URI = "ws://example.invalid"


class _RecordingConnection:
    """Stand-in for a `websockets` client connection that captures payloads."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, payload: str, /) -> None:
        """Capture `payload` instead of writing it to a socket."""
        self.sent.append(payload)

    def close(self) -> None:
        """Accept the sender's teardown call."""


class _ClosedConnection:
    """Stand-in for a connection the streamer has already closed."""

    def __init__(self, close: Close | None) -> None:
        self._close = close

    def send(self, _payload: str, /) -> None:
        """Fail the way `websockets` does once the connection is closed."""
        raise websockets.exceptions.ConnectionClosedError(self._close, None)

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
        connection = _RecordingConnection()

        with WebSocketCommandSender(_URI, lambda _: connection) as sender:
            sender.send(Command.TURN_LEFT, 50)
            sender.send(Command.BRAKE, None)

        assert recorded == [Command.TURN_LEFT, Command.BRAKE]

    def test_says_why_the_streamer_closed_the_connection(self) -> None:
        connection = _ClosedConnection(
            Close(CloseCode.TRY_AGAIN_LATER, "another driver is connected")
        )

        with (
            WebSocketCommandSender(_URI, lambda _: connection) as sender,
            pytest.raises(DriveConnectionClosedError, match="another driver"),
        ):
            sender.send(Command.BRAKE, None)

    def test_reports_a_lost_connection_without_a_reason(self) -> None:
        connection = _ClosedConnection(None)

        with (
            WebSocketCommandSender(_URI, lambda _: connection) as sender,
            pytest.raises(DriveConnectionClosedError, match="connection lost"),
        ):
            sender.send(Command.BRAKE, None)
