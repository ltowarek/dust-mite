"""controller module."""

import json
import logging
import os
from enum import Enum

import websockets.sync.client
from opentelemetry import trace
from pydualsense import pydualsense

from .tracing import configure_tracing, inject_trace_context

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

tracer = trace.get_tracer(__name__)


class Command(Enum):
    """Car commands."""

    ADVANCE = 1
    RETREAT = 2
    BRAKE = 3
    TURN_LEFT = 4
    TURN_RIGHT = 5
    LOOK_HORIZONTALLY = 6
    LOOK_VERTICALLY = 7


def interpolate(
    value: float, in_min: float, in_max: float, out_min: float, out_max: float
) -> float:
    """Interpolate value from [in_min, in_max] range to [out_min, out_max] range."""
    return (value - in_min) * (out_max - out_min) / (in_max - in_min) + out_min


@tracer.start_as_current_span("controller.send_command")
def send_command(
    ws_conn: websockets.sync.client.ClientConnection,
    command: Command,
    value: int | None,
) -> None:
    """Send a command to the car."""
    span = trace.get_current_span()
    span.set_attribute("command_name", command.name)
    if value is not None:
        span.set_attribute("command_value", value)

    payload = {"command": command.value, "value": value}
    payload = inject_trace_context(payload)

    ws_conn.send(json.dumps(payload))


def read_input(ds: pydualsense, analog_dead_zone: int) -> tuple[Command, int | None]:
    """Read DualSense state and return the current command and value."""
    command = Command.BRAKE
    value = None

    # TODO: Split car and camera commands
    # Currently there is no way to drive a car and look around
    # What's more, you can't look horizontally and vertically and the same time
    if ds.state.DpadUp > 0:
        command, value = Command.ADVANCE, 50
    elif ds.state.DpadRight:
        command, value = Command.TURN_RIGHT, 50
    elif ds.state.DpadDown:
        command, value = Command.RETREAT, 50
    elif ds.state.DpadLeft:
        command, value = Command.TURN_LEFT, 50
    elif not (-analog_dead_zone <= ds.state.LX <= analog_dead_zone):
        if ds.state.LX < 0:
            command = Command.TURN_LEFT
            value = int(interpolate(ds.state.LX, -128, 0, 100, 0))
        else:
            command = Command.TURN_RIGHT
            value = int(interpolate(ds.state.LX, 0, 127, 0, 100))
    elif not (-analog_dead_zone <= ds.state.RX <= analog_dead_zone):
        command = Command.LOOK_HORIZONTALLY
        value = int(interpolate(ds.state.RX, -128, 127, -90, 90))
    elif not (-analog_dead_zone <= ds.state.RY <= analog_dead_zone):
        command = Command.LOOK_VERTICALLY
        value = int(interpolate(ds.state.RY, -128, 127, 90, -90))
    elif ds.state.R2 > 0:
        command = Command.ADVANCE
        value = int(interpolate(ds.state.R2, 0, 255, 0, 100))

    return command, value


def control(ws_conn: websockets.sync.client.ClientConnection, ds: pydualsense) -> None:
    """Read gamepad input in a loop and send commands to the car."""
    analog_dead_zone = 5
    last_command = Command.BRAKE
    last_value = None

    while not ds.state.ps:
        command, value = read_input(ds, analog_dead_zone)

        if (command != last_command) or (value != last_value):
            logger.debug("Sending new command with value: %s - %s", command.name, value)
            send_command(ws_conn, command, value)
            last_command = command
            last_value = value


def main() -> None:
    """Run the main entry point."""
    configure_tracing("dust-mite-controller")
    controller_client_uri = os.environ["CONTROLLER_CLIENT_URI"]

    ws_conn = websockets.sync.client.connect(controller_client_uri)

    ds = pydualsense()
    ds.init()

    control(ws_conn, ds)

    ds.close()
    ws_conn.close()


if __name__ == "__main__":
    main()
