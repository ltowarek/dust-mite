"""The streamer's side of the car: its endpoints and its message format."""

from .tracing import inject_trace_context
from .websocket_message import WebSocketMessage


def prepare_drive_command(command: WebSocketMessage) -> WebSocketMessage:
    """Build a Drive command for the car with trace context."""
    return inject_trace_context(command)
