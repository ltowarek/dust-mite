import pytest
import websockets.exceptions
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from websockets.frames import Close, CloseCode

from controller.command import Command
from controller.senders import (
    DriveConnectionClosedError,
    WebSocketCommandSender,
)

from .conftest import counter_values_by_command


class _ConnectionStub:
    """Stand-in for a `websockets` client connection that accepts every send."""

    def send(self, _payload: str, /) -> None:
        """Accept `_payload` instead of writing it to a socket."""


class _ClosedConnectionStub:
    """Stand-in for a connection the streamer has already closed."""

    def __init__(self, close: Close | None) -> None:
        self._close = close

    def send(self, _payload: str, /) -> None:
        """Fail the way `websockets` does once the connection is closed."""
        raise websockets.exceptions.ConnectionClosedError(self._close, None)


class TestWebSocketCommandSender:
    def test_records_a_metric_for_every_command_sent(
        self, reader: InMemoryMetricReader
    ) -> None:
        sender = WebSocketCommandSender(_ConnectionStub())

        sender.send(Command.TURN_LEFT, 50)
        sender.send(Command.BRAKE, None)

        assert counter_values_by_command(reader, "dust_mite_commands_sent") == {
            "TURN_LEFT": 1,
            "BRAKE": 1,
        }

    def test_says_why_the_streamer_closed_the_connection(self) -> None:
        sender = WebSocketCommandSender(
            _ClosedConnectionStub(
                Close(CloseCode.TRY_AGAIN_LATER, "another driver is connected")
            )
        )

        with pytest.raises(DriveConnectionClosedError, match="another driver"):
            sender.send(Command.BRAKE, None)

    def test_reports_a_lost_connection_without_a_reason(self) -> None:
        sender = WebSocketCommandSender(_ClosedConnectionStub(None))

        with pytest.raises(DriveConnectionClosedError, match="connection lost"):
            sender.send(Command.BRAKE, None)
