"""Collision monitor: keeps drive commands from advancing into an obstacle."""

import threading
from typing import Any

from .command import Command


class CollisionMonitor:
    """Turns ADVANCE into BRAKE while an obstacle is close ahead.

    Distances are in centimeters, as reported by the car's ultrasonic sensor.
    Stopping starts below `STOP_DISTANCE_CM` and lasts until the obstacle is
    at least `RESUME_DISTANCE_CM` away, so sensor jitter around a single
    cutoff doesn't flip it on and off. RETREAT and the turns always pass
    through, so the operator can back away.
    """

    STOP_DISTANCE_CM = 5
    RESUME_DISTANCE_CM = 10

    def __init__(self) -> None:
        """Initialize the object."""
        self._lock = threading.Lock()
        self._stopping = False

    @property
    def stopping(self) -> bool:
        """Whether ADVANCE is currently being turned into BRAKE."""
        with self._lock:
            return self._stopping

    def update(self, distance_ahead_cm: float) -> bool:
        """Take a new distance reading; return whether `stopping` changed.

        A negative reading means the sensor received no echo and leaves the
        state unchanged.
        """
        with self._lock:
            if distance_ahead_cm < 0:
                return False
            if self._stopping:
                stopping = distance_ahead_cm < self.RESUME_DISTANCE_CM
            else:
                stopping = distance_ahead_cm < self.STOP_DISTANCE_CM
            changed = stopping != self._stopping
            self._stopping = stopping
            return changed

    def filter(self, command_packet: dict[str, Any]) -> dict[str, Any]:
        """Return the command to send to the car in place of `command_packet`."""
        if self.stopping and command_packet.get("command") == Command.ADVANCE.value:
            return {"command": Command.BRAKE.value, "value": None}
        return command_packet
