"""controller module."""

import json
import logging
import os
from typing import Any

import websockets.sync.client
from pydualsense import pydualsense

logging.basicConfig(level=logging.DEBUG)

logger = logging.getLogger(__name__)

ESP32_ADDRESS = "<ESP32_ADDRESS>"


COMMAND_ADVANCE = 1
COMMAND_RETREAT = 2
COMMAND_BRAKE = 3
COMMAND_TURN_LEFT = 4
COMMAND_TURN_RIGHT = 5


ws_conn: websockets.sync.client.ClientConnection | None = None


# TODO: There are race conditions e.g. BRAKE is sent before ADVANCE
def send_command(payload: dict[str, Any]) -> None:
    """Send command to the car.

    :param payload: payload sent through query parameters
    """
    assert ws_conn is not None
    ws_conn.send(json.dumps(payload))


def dpad_up_pressed(state: bool) -> None:  # noqa: FBT001
    """Handle dpad up event.

    :param state: True if pressed else False
    """
    logger.debug("DPAD UP - %s", state)
    command = {
        "command": COMMAND_ADVANCE if state else COMMAND_BRAKE,
        "value": None,
    }
    send_command(command)


def dpad_right_pressed(state: bool) -> None:  # noqa: FBT001
    """Handle dpad right event.

    :param state: True if pressed else False
    """
    logger.debug("DPAD RIGHT - %s", state)
    command = {
        "command": COMMAND_TURN_RIGHT if state else COMMAND_BRAKE,
        "value": None,
    }
    send_command(command)


def dpad_down_pressed(state: bool) -> None:  # noqa: FBT001
    """Handle dpad down event.

    :param state: True if pressed else False
    """
    logger.debug("DPAD DOWN - %s", state)
    command = {
        "command": COMMAND_RETREAT if state else COMMAND_BRAKE,
        "value": None,
    }
    send_command(command)


def dpad_left_pressed(state: bool) -> None:  # noqa: FBT001
    """Handle dpad left event.

    :param state: True if pressed else False
    """
    logger.debug("DPAD LEFT - %s", state)
    command = {
        "command": COMMAND_TURN_LEFT if state else COMMAND_BRAKE,
        "value": None,
    }
    send_command(command)


if __name__ == "__main__":
    ESP32_ADDRESS = os.environ["ESP32_ADDRESS"]
    ws_conn = websockets.sync.client.connect(ESP32_ADDRESS)

    ds = pydualsense()
    ds.init()

    ds.dpad_up += dpad_up_pressed
    ds.dpad_right += dpad_right_pressed
    ds.dpad_down += dpad_down_pressed
    ds.dpad_left += dpad_left_pressed

    while not ds.state.ps:
        ...

    ds.close()
    ws_conn.close()
