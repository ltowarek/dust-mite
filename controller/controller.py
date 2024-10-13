from pydualsense import pydualsense
import requests

ESP32_ADDRESS = "<ESP32_ADDRESS>"

COMMAND_START = "1"
COMMAND_END = "2"
COMMAND_TURN = "3"
COMMAND_BRAKE = "4"
COMMAND_ACCELERATE = "5"


def send_command(payload):
    r = requests.get(ESP32_ADDRESS, params=payload)
    r.raise_for_status()


def cross_pressed(state):
    print(f"CROSS - {state}")
    command = {
        "command": COMMAND_START if state else COMMAND_END,
    }
    send_command(command)


def left_joystick_changed(x, y):
    print(f"L - {x} - {y}")
    command = {
        "command": COMMAND_TURN,
        "value": x,
    }
    send_command(command)


def l2_changed(value):
    print(f"L2 - {value}")
    command = {
        "command": COMMAND_BRAKE,
        "value": value,
    }
    send_command(command)


def r2_changed(value):
    print(f"R2 - {value}")
    command = {
        "command": COMMAND_ACCELERATE,
        "value": value,
    }
    send_command(command)


ds = pydualsense()
ds.init()

ds.cross_pressed += cross_pressed
ds.left_joystick_changed += left_joystick_changed
ds.l2_changed += l2_changed
ds.r2_changed += r2_changed

while not ds.state.ps:
    ...

ds.close()
