import base64
import json

import cv2
import numpy as np

from controller.streamer import camera_message, telemetry_message


def _camera_packet() -> str:
    jpeg = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))[1].tobytes()
    return json.dumps({"data": base64.b64encode(jpeg).decode("ascii")})


def test_a_camera_frame_becomes_a_stream_message() -> None:
    assert camera_message(_camera_packet())["type"] == "stream"


def test_a_telemetry_packet_becomes_a_telemetry_message() -> None:
    telemetry = {"distance_ahead": 100, "speed": 0.0}

    assert telemetry_message(json.dumps(telemetry))["data"] == telemetry
