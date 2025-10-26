"""controller module."""

import json
import logging
import os
from enum import Enum
from typing import Any

import websockets.sync.client
from pydualsense import pydualsense

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

ESP32_ADDRESS = os.environ.get("ESP32_ADDRESS", "ws://192.168.50.66")


class Command(Enum):
    """Car commands."""

    ADVANCE = 1
    RETREAT = 2
    BRAKE = 3
    TURN_LEFT = 4
    TURN_RIGHT = 5
    LOOK_HORIZONTALLY = 6
    LOOK_VERTICALLY = 7


ws_conn: websockets.sync.client.ClientConnection | None = None


def send_command(payload: dict[str, Any]) -> None:
    """Send command to the car.

    :param payload: payload sent through query parameters
    """
    assert ws_conn is not None
    ws_conn.send(json.dumps(payload))


def interpolate(
    value: float, in_min: float, in_max: float, out_min: float, out_max: float
) -> float:
    """Interpolate value from [in_min, in_max] range to [out_min, out_max] range."""
    return (value - in_min) * (out_max - out_min) / (in_max - in_min) + out_min


if __name__ == "__main__":
    ws_conn = websockets.sync.client.connect(ESP32_ADDRESS)

    ds = pydualsense()
    ds.init()

    command: Command
    value: int | None

    lx_dead_zone = 5
    last_command = Command.BRAKE
    last_value = None
    while not ds.state.ps:
        if ds.state.DpadUp > 0:
            command = Command.ADVANCE
            value = 50
        elif ds.state.DpadRight:
            command = Command.TURN_RIGHT
            value = 50
        elif ds.state.DpadDown:
            command = Command.RETREAT
            value = 50
        elif ds.state.DpadLeft:
            command = Command.TURN_LEFT
            value = 50
        elif not (-lx_dead_zone <= ds.state.LX <= lx_dead_zone):
            if ds.state.LX < 0:
                command = Command.TURN_LEFT
                value = int(interpolate(ds.state.LX, -128, 0, 100, 0))
            else:
                command = Command.TURN_RIGHT
                value = int(interpolate(ds.state.LX, 0, 127, 0, 100))
        # TODO: Split car and camera commands
        # Currently there is no way to drive a car and look around
        # What's more, you can't look horizontally and vertically and the same time
        elif ds.state.RX:
            command = Command.LOOK_HORIZONTALLY
            value = int(interpolate(ds.state.RX, -128, 127, -90, 90))
        elif ds.state.RY:
            command = Command.LOOK_VERTICALLY
            value = int(interpolate(ds.state.RY, -128, 127, 90, -90))
        elif ds.state.R2 > 0:
            command = Command.ADVANCE
            value = int(interpolate(ds.state.R2, 0, 255, 0, 100))
        else:
            command = Command.BRAKE
            value = None

        if (command != last_command) or (value != last_value):
            logger.debug("Sending new command with value: %s - %s", command.name, value)
            send_command(
                {
                    "command": command.value,
                    "value": value,
                }
            )
            last_command = command
            last_value = value

    ds.close()
    ws_conn.close()
