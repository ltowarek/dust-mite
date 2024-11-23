"""controller module."""

import json
import logging
import os
from typing import Any

import websockets.sync.client
from pydualsense import pydualsense

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

ESP32_ADDRESS = "<ESP32_ADDRESS>"


COMMAND_ADVANCE = 1
COMMAND_RETREAT = 2
COMMAND_BRAKE = 3
COMMAND_TURN_LEFT = 4
COMMAND_TURN_RIGHT = 5


ws_conn: websockets.sync.client.ClientConnection | None = None


def send_command(payload: dict[str, Any]) -> None:
    """Send command to the car.

    :param payload: payload sent through query parameters
    """
    assert ws_conn is not None
    ws_conn.send(json.dumps(payload))


if __name__ == "__main__":
    ESP32_ADDRESS = os.environ["ESP32_ADDRESS"]
    ws_conn = websockets.sync.client.connect(ESP32_ADDRESS)

    ds = pydualsense()
    ds.init()

    last_command = COMMAND_BRAKE
    last_value = None
    while not ds.state.ps:
        if ds.state.DpadUp > 0:
            command = COMMAND_ADVANCE
        elif ds.state.DpadRight:
            command = COMMAND_TURN_RIGHT
        elif ds.state.DpadDown:
            command = COMMAND_RETREAT
        elif ds.state.DpadLeft:
            command = COMMAND_TURN_LEFT
        else:
            command = COMMAND_BRAKE
            value = None

        if (command != last_command) or (value != last_value):
            logger.debug("Sending new command with value: %s - %s", command, value)
            send_command(
                {
                    "command": command,
                    "value": value,
                }
            )
            last_command = command
            last_value = value

    ds.close()
    ws_conn.close()
