import json

import cv2
import numpy as np
import pytest

from controller.mjpeg import CameraStreamPart
from controller.streamer import (
    StreamerSettings,
    relay_camera_part,
    relay_telemetry_message,
)

_CAR_TRACE_ID = "0af7651916cd43dd8448eb211c80319c"


def _camera_part() -> CameraStreamPart:
    jpeg = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))[1].tobytes()
    return CameraStreamPart(
        {"traceparent": f"00-{_CAR_TRACE_ID}-b7ad6b7169203331-01"}, jpeg
    )


def test_a_camera_part_becomes_a_processed_jpeg() -> None:
    assert relay_camera_part(_camera_part()).jpeg[:2] == b"\xff\xd8"


def test_a_processed_part_continues_the_car_trace() -> None:
    traceparent = relay_camera_part(_camera_part()).headers["traceparent"]

    assert traceparent.split("-")[1] == _CAR_TRACE_ID


def test_a_telemetry_message_from_the_car_becomes_a_client_telemetry_message() -> None:
    telemetry = {"distance_ahead": 100, "speed": 0.0}

    assert relay_telemetry_message(json.dumps(telemetry))["data"] == telemetry


_STREAMER_ENV = {
    "STREAM_CLIENT_URI": "http://car.invalid/stream",
    "TELEMETRY_CLIENT_URI": "ws://car.invalid/telemetry",
    "DRIVE_CLIENT_URI": "ws://car.invalid/drive",
    "PROFILING_ENABLED": "1",
}


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        pytest.param("camera_uri", "http://car.invalid/stream", id="camera"),
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
