"""Command senders: destinations for driving commands from the gamepad CLI."""

import json
from typing import Protocol

import websockets.exceptions
from opentelemetry import trace
from opentelemetry.semconv.attributes.network_attributes import NETWORK_PROTOCOL_NAME

from .command import Command
from .metrics import record_command_sent
from .tracing import inject_trace_context

tracer = trace.get_tracer(__name__)


class _Connection(Protocol):
    """The subset of a `websockets` client connection the sender writes through."""

    def send(self, message: str, /) -> None: ...


class DriveConnectionClosedError(Exception):
    """The connection commands are sent over was closed, with the reason given."""


class CommandSender(Protocol):
    """Destination for driving commands."""

    def send(self, command: Command, value: int | None) -> None:
        """Send a command to the car."""
        ...


class WebSocketCommandSender:
    """Send commands to the car over an open WebSocket `connection`."""

    def __init__(self, connection: _Connection) -> None:
        """Initialize the object."""
        self._connection = connection

    @tracer.start_as_current_span("controller.send_command")
    def send(self, command: Command, value: int | None) -> None:
        """Send a command to the car."""
        span = trace.get_current_span()
        span.set_attribute(NETWORK_PROTOCOL_NAME, "websocket")
        span.set_attribute("command_name", command.name)
        if value is not None:
            span.set_attribute("command_value", value)

        payload = {"command": command.value, "value": value}
        payload = inject_trace_context(payload)

        try:
            self._connection.send(json.dumps(payload))
        except websockets.exceptions.ConnectionClosed as e:
            reason = e.rcvd.reason if e.rcvd is not None else ""
            raise DriveConnectionClosedError(reason or "connection lost") from e
        record_command_sent(command)
