"""The JSON object the car, the streamer and its clients exchange."""

from typing import Any

# One JSON object carried by a WebSocket message: a drive command, a camera
# frame, a telemetry reading or a collision-monitor state.
type Packet = dict[str, Any]
