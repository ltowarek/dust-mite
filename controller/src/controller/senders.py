"""Sending Drive commands from the gamepad CLI."""

import json
from typing import Protocol

from opentelemetry import trace
from opentelemetry.semconv.attributes.network_attributes import NETWORK_PROTOCOL_NAME

from .command import DriveCommand
from .metrics import record_command_sent
from .tracing import inject_trace_context

tracer = trace.get_tracer(__name__)


class _Connection(Protocol):
    """The subset of a `websockets` client connection the sender writes through."""

    async def send(self, message: str, /) -> None: ...


@tracer.start_as_current_span("controller.send_command")
async def send_command(connection: _Connection, drive_command: DriveCommand) -> None:
    """Send a Drive command to the car over an open WebSocket `connection`."""
    command, value = drive_command
    span = trace.get_current_span()
    span.set_attribute(NETWORK_PROTOCOL_NAME, "websocket")
    span.set_attribute("command_name", command.name)
    if value is not None:
        span.set_attribute("command_value", value)

    payload = {"command": command.value, "value": value}
    payload = inject_trace_context(payload)

    await connection.send(json.dumps(payload))
    record_command_sent(command)
