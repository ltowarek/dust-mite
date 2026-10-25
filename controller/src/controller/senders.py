"""Command senders: destinations for driving commands from the gamepad CLI."""

import json
from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

import websockets.exceptions
import websockets.sync.client
from opentelemetry import trace
from opentelemetry.semconv.attributes.network_attributes import NETWORK_PROTOCOL_NAME

from .command import Command
from .metrics import record_command_sent
from .tracing import inject_trace_context

tracer = trace.get_tracer(__name__)


class _Connection(Protocol):
    """The subset of a `websockets` client connection the sender writes through.

    A structural type rather than `WebSocketClient` itself, so tests can
    pass a test double through `WebSocketCommandSender`'s `connect` argument
    instead of opening a live socket.
    """

    def send(self, message: str, /) -> None: ...
    def close(self) -> None: ...


class SenderNotConnectedError(Exception):
    """A command sender was used before `connect()` or outside its context."""


class DriveConnectionClosedError(Exception):
    """The connection commands are sent over was closed, with the reason given."""


class CommandSender(Protocol):
    """Destination for driving commands."""

    def send(self, command: Command, value: int | None) -> None:
        """Send a command to the car."""
        ...


class WebSocketCommandSender:
    """Send commands to the car over a WebSocket connection.

    Use as a context manager: connects to `uri` on entry, closes on exit.
    `connect` opens the connection; tests pass one that returns a test double.
    """

    def __init__(
        self,
        uri: str,
        connect: Callable[[str], _Connection] = websockets.sync.client.connect,
    ) -> None:
        """Initialize the object."""
        self._uri = uri
        self._connect = connect
        self._ws_conn: _Connection | None = None

    def connect(self) -> None:
        """Connect to the car."""
        self._ws_conn = self._connect(self._uri)

    def close(self) -> None:
        """Close the connection."""
        self._require_connection().close()

    def __enter__(self) -> Self:
        """Connect in a context manager."""
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: TracebackType | None,
    ) -> None:
        """Close the connection in a context manager."""
        self.close()

    @tracer.start_as_current_span("controller.send_command")
    def send(self, command: Command, value: int | None) -> None:
        """Send a command to the car."""
        connection = self._require_connection()

        span = trace.get_current_span()
        span.set_attribute(NETWORK_PROTOCOL_NAME, "websocket")
        span.set_attribute("command_name", command.name)
        if value is not None:
            span.set_attribute("command_value", value)

        payload = {"command": command.value, "value": value}
        payload = inject_trace_context(payload)

        try:
            connection.send(json.dumps(payload))
        except websockets.exceptions.ConnectionClosed as e:
            reason = e.rcvd.reason if e.rcvd is not None else ""
            raise DriveConnectionClosedError(reason or "connection lost") from e
        record_command_sent(command)

    def _require_connection(self) -> _Connection:
        if self._ws_conn is None:
            msg = "connect() has not been called"
            raise SenderNotConnectedError(msg)
        return self._ws_conn
