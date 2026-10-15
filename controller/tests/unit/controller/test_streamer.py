import base64
import json

import cv2
import numpy as np
import pytest

from controller.streamer import (
    StreamerSettings,
    relay_camera_packet,
    relay_telemetry_packet,
)


def _camera_packet() -> str:
    jpeg = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))[1].tobytes()
    return json.dumps({"data": base64.b64encode(jpeg).decode("ascii")})


def test_a_camera_packet_becomes_a_stream_packet() -> None:
    assert relay_camera_packet(_camera_packet())["type"] == "stream"


def test_a_telemetry_packet_from_the_car_becomes_a_client_telemetry_packet() -> None:
    telemetry = {"distance_ahead": 100, "speed": 0.0}

    assert relay_telemetry_packet(json.dumps(telemetry))["data"] == telemetry


_STREAMER_ENV = {
    "STREAM_CLIENT_URI": "ws://car.invalid/camera",
    "TELEMETRY_CLIENT_URI": "ws://car.invalid/telemetry",
    "DRIVE_CLIENT_URI": "ws://car.invalid/drive",
    "PROFILING_ENABLED": "1",
}


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        pytest.param("camera_uri", "ws://car.invalid/camera", id="camera"),
        pytest.param("telemetry_uri", "ws://car.invalid/telemetry", id="telemetry"),
        pytest.param("drive_uri", "ws://car.invalid/drive", id="drive"),
    ],
)
def test_settings_read_each_car_endpoint_uri(field: str, expected: str) -> None:
    settings = StreamerSettings.from_env(_STREAMER_ENV)

    assert getattr(settings, field) == expected


def test_settings_read_the_observability_settings() -> None:
    settings = StreamerSettings.from_env(_STREAMER_ENV)

    assert settings.observability.profiling_enabled is True


@pytest.mark.parametrize(
    "variable", ["STREAM_CLIENT_URI", "TELEMETRY_CLIENT_URI", "DRIVE_CLIENT_URI"]
)
def test_settings_require_each_car_endpoint_uri(variable: str) -> None:
    environ = {k: v for k, v in _STREAMER_ENV.items() if k != variable}

    with pytest.raises(KeyError, match=variable):
        StreamerSettings.from_env(environ)
