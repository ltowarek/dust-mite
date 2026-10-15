"""Decides which drive commands reach the car."""

import contextlib
import threading
from collections.abc import Callable, Iterator
from typing import Any

from opentelemetry import trace

from .car import CarFeed, Message, prepare_command_packet
from .collision_monitor import CollisionMonitor
from .command import Command
from .metrics import record_command_blocked, record_command_sent
from .subject import Subject
from .tracing import extract_trace_context, inject_trace_context

tracer = trace.get_tracer(__name__)


DRIVER_ALREADY_CONNECTED = "another driver is connected"


class DriverAlreadyConnectedError(Exception):
    """Another driver already holds the CommandArbiter."""


class CommandArbiter:
    """Decides which drive commands reach the car.

    One driver at a time may claim it; another is refused until the first
    releases it. Every command goes through `collision_monitor` first and is
    then published on `commands`. While a driver holds the claim, the arbiter
    keeps `collision_monitor` fed from the telemetry feed.
    `collision_state` carries whether the monitor is stopping the car.
    """

    def __init__(
        self,
        commands: Subject[Message],
        telemetry: CarFeed | Subject[Message],
        collision_monitor: CollisionMonitor,
    ) -> None:
        """Initialize the object."""
        self._commands = commands
        self._telemetry = telemetry
        self._collision_monitor = collision_monitor
        self._lock = threading.Lock()
        self._claimed = False
        # Race: only changes are published, so a client that subscribes after
        # the latest change sees no collision state until the next one.
        self.collision_state: Subject[Message] = Subject()

    @contextlib.contextmanager
    def claim(self) -> Iterator[Callable[[Message], None]]:
        """Hold the arbiter for the context; yield a function that sends commands.

        Raises `DriverAlreadyConnectedError` if another driver holds it.
        """
        with self._lock:
            if self._claimed:
                raise DriverAlreadyConnectedError(DRIVER_ALREADY_CONNECTED)
            self._claimed = True
        try:
            with self._telemetry.subscription(self._on_telemetry):
                yield self._submit
        finally:
            if self._collision_monitor.stopping:
                self._collision_monitor.reset()
                self._publish_collision_state()
            with self._lock:
                self._claimed = False

    def _submit(self, command_packet: dict[str, Any]) -> None:
        operator_context = extract_trace_context(command_packet)
        with tracer.start_as_current_span(
            "streamer.handle_drive_command", context=operator_context
        ) as span:
            requested = Command(command_packet["command"])
            command_packet = self._collision_monitor.filter(command_packet)
            command = Command(command_packet["command"])
            span.set_attribute("network.protocol.name", "websocket")
            span.set_attribute("operator_command_name", requested.name)
            span.set_attribute("command_name", command.name)
            span.set_attribute(
                "collision_monitor.stopping", self._collision_monitor.stopping
            )
            if command != requested:
                record_command_blocked(requested)
            self._commands.publish(prepare_command_packet(command_packet))
            record_command_sent(command)

    def _on_telemetry(self, message: dict[str, Any]) -> None:
        if self._collision_monitor.update(message["data"]["distance_ahead"]):
            self._publish_collision_state()

    def _publish_collision_state(self) -> None:
        self.collision_state.publish(
            inject_trace_context(
                {
                    "type": "collision_monitor",
                    "stopping": self._collision_monitor.stopping,
                }
            )
        )
