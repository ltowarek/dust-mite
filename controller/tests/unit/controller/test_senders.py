import pytest
import websockets.exceptions
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from websockets.frames import Close, CloseCode

from controller.command import Command
from controller.senders import DriveConnectionClosedError, WebSocketCommandSender

from .conftest import counter_values_by_command

_URI = "ws://example.invalid"


class _ConnectionStub:
    """Stand-in for a `websockets` client connection that accepts every send."""

    def send(self, _payload: str, /) -> None:
        """Accept `_payload` instead of writing it to a socket."""

    def close(self) -> None:
        """Accept the sender's teardown call."""


class _ClosedConnectionStub:
    """Stand-in for a connection the streamer has already closed."""

    def __init__(self, close: Close | None) -> None:
        self._close = close

    def send(self, _payload: str, /) -> None:
        """Fail the way `websockets` does once the connection is closed."""
        raise websockets.exceptions.ConnectionClosedError(self._close, None)

    def close(self) -> None:
        """Accept the sender's teardown call."""


class TestWebSocketCommandSender:
    def test_records_a_metric_for_every_command_sent(
        self, reader: InMemoryMetricReader
    ) -> None:
        connection = _ConnectionStub()

        with WebSocketCommandSender(_URI, lambda _: connection) as sender:
            sender.send(Command.TURN_LEFT, 50)
            sender.send(Command.BRAKE, None)

        assert counter_values_by_command(reader, "dust_mite_commands_sent") == {
            "TURN_LEFT": 1,
            "BRAKE": 1,
        }

    def test_says_why_the_streamer_closed_the_connection(self) -> None:
        connection = _ClosedConnectionStub(
            Close(CloseCode.TRY_AGAIN_LATER, "another driver is connected")
        )

        with (
            WebSocketCommandSender(_URI, lambda _: connection) as sender,
            pytest.raises(DriveConnectionClosedError, match="another driver"),
        ):
            sender.send(Command.BRAKE, None)

    def test_reports_a_lost_connection_without_a_reason(self) -> None:
        connection = _ClosedConnectionStub(None)

        with (
            WebSocketCommandSender(_URI, lambda _: connection) as sender,
            pytest.raises(DriveConnectionClosedError, match="connection lost"),
        ):
            sender.send(Command.BRAKE, None)
