"""Command senders: destinations for driving commands from the gamepad CLI."""

import json
from types import TracebackType
from typing import Protocol, Self

import websockets.sync.client
from opentelemetry import trace

from .command import Command
from .tracing import inject_trace_context

tracer = trace.get_tracer(__name__)


class CommandSender(Protocol):
    """Destination for driving commands."""

    def send(self, command: Command, value: int | None) -> None:
        """Send a command to the car."""
        ...


class WebSocketCommandSender:
    """Send commands to the car over a WebSocket connection.

    Use as a context manager: connects to `uri` on entry, closes on exit.
    """

    def __init__(self, uri: str) -> None:
        """Initialize the object."""
        self._uri = uri
        self._ws_conn: websockets.sync.client.ClientConnection | None = None

    def connect(self) -> None:
        """Connect to the car."""
        self._ws_conn = websockets.sync.client.connect(self._uri)

    def close(self) -> None:
        """Close the connection."""
        assert self._ws_conn is not None
        self._ws_conn.close()

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
        assert self._ws_conn is not None

        span = trace.get_current_span()
        span.set_attribute("network.protocol.name", "websocket")
        span.set_attribute("command_name", command.name)
        if value is not None:
            span.set_attribute("command_value", value)

        payload = {"command": command.value, "value": value}
        payload = inject_trace_context(payload)

        self._ws_conn.send(json.dumps(payload))


class InMemoryCommandSender:
    """Command sender that records sent commands instead of transmitting them.

    Useful for local development and tests that need to drive the control
    loop without a real websocket connection or car.
    """

    def __init__(self) -> None:
        """Initialize the object."""
        self.sent: list[tuple[Command, int | None]] = []

    def send(self, command: Command, value: int | None) -> None:
        """Record a command instead of sending it anywhere."""
        self.sent.append((command, value))
