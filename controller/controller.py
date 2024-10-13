from pydualsense import pydualsense
import requests

ESP32_ADDRESS = "<ESP32_ADDRESS>"

COMMAND_START = "1"
COMMAND_END = "2"


def cross_pressed(state):
    command = COMMAND_START if state else COMMAND_END
    r = requests.get(ESP32_ADDRESS, params={"command": command})
    r.raise_for_status()


ds = pydualsense()
ds.init()

ds.cross_pressed += cross_pressed

while not ds.state.ps:
    ...

ds.close()
