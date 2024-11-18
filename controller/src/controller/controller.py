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


COMMAND_START = 1
COMMAND_END = 2
COMMAND_TURN = 3
COMMAND_BRAKE = 4
COMMAND_ACCELERATE = 5


ws_conn: websockets.sync.client.ClientConnection | None = None


def send_command(payload: dict[str, Any]) -> None:
    """Send command to the car.

    :param payload: payload sent through query parameters
    """
    assert ws_conn is not None
    ws_conn.send(json.dumps(payload))


def cross_pressed(state: bool) -> None:  # noqa: FBT001
    """Handle cross event.

    :param state: True if pressed else False
    """
    logger.debug("CROSS - %s", state)
    command = {
        "command": COMMAND_START if state else COMMAND_END,
        "value": None,
    }
    send_command(command)


def left_joystick_changed(x: int, y: int) -> None:
    """Handle L event.

    :param x: value between -128(left) and 127(right)
    :param y: value between -128(down) and 127(up)
    """
    logger.debug("L - %d - %d", x, y)
    command = {
        "command": COMMAND_TURN,
        "value": x,
    }
    send_command(command)


def l2_changed(value: int) -> None:
    """Handle L2 event.

    :param value: value between 0 and 255
    """
    logger.debug("L2 - %d", value)
    command = {
        "command": COMMAND_BRAKE,
        "value": value,
    }
    send_command(command)


def r2_changed(value: int) -> None:
    """Handle R2 event.

    :param value: value between 0 and 255
    """
    logger.debug("R2 - %d", value)
    command = {
        "command": COMMAND_ACCELERATE,
        "value": value,
    }
    send_command(command)


if __name__ == "__main__":
    ESP32_ADDRESS = os.environ["ESP32_ADDRESS"]
    ws_conn = websockets.sync.client.connect(ESP32_ADDRESS)

    ds = pydualsense()
    ds.init()

    ds.cross_pressed += cross_pressed
    ds.left_joystick_changed += left_joystick_changed
    ds.l2_changed += l2_changed
    ds.r2_changed += r2_changed

    while not ds.state.ps:
        ...

    ds.close()
    ws_conn.close()
