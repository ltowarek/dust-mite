"""The JSON WebSocket message the car, the streamer and its clients exchange."""

from typing import Any

# One JSON object carried by a WebSocket message: a Drive command, a camera
# frame, a Telemetry message or a Collision-monitor message.
type WebSocketMessage = dict[str, Any]
