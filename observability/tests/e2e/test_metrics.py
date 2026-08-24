import pytest

from tests.helpers.query import MIMIR_UID, has_metrics, query

CAR_METRICS = [
    "dust_mite_free_heap_bytes",
    "dust_mite_min_free_heap_bytes",
    "dust_mite_largest_free_block_bytes",
    "dust_mite_internal_free_heap_bytes",
    "dust_mite_free_psram_bytes",
    "dust_mite_uptime",
    "dust_mite_temperature",
    "dust_mite_task_cpu_usage",
    "dust_mite_task_priority",
    "dust_mite_rssi",
    "dust_mite_speed",
    "dust_mite_distance_ahead",
    "dust_mite_accelerometer_x",
    "dust_mite_accelerometer_y",
    "dust_mite_accelerometer_z",
    "dust_mite_magnetometer_x",
    "dust_mite_magnetometer_y",
    "dust_mite_magnetometer_z",
    "dust_mite_gyroscope_x",
    "dust_mite_gyroscope_y",
    "dust_mite_gyroscope_z",
    "dust_mite_frames_captured",
    "dust_mite_camera_frame_size_bytes",
    "dust_mite_camera_frame_buffer_bytes",
    "dust_mite_frames_sent",
]
STREAMER_METRICS = [
    "dust_mite_frames_processed",
    "dust_mite_telemetry_packets_received",
    "dust_mite_commands_sent",
]
WEB_METRICS = ["dust_mite_frames_displayed"]


@pytest.mark.dut
@pytest.mark.parametrize("metric_name", CAR_METRICS)
def test_car_metric_has_metrics(metric_name: str) -> None:
    assert has_metrics(
        query(MIMIR_UID, "prometheus", {"expr": metric_name, "instant": True})
    )


@pytest.mark.dut
@pytest.mark.parametrize("metric_name", STREAMER_METRICS)
def test_streamer_metric_has_metrics(metric_name: str) -> None:
    assert has_metrics(
        query(MIMIR_UID, "prometheus", {"expr": metric_name, "instant": True})
    )


@pytest.mark.dut
@pytest.mark.parametrize("metric_name", WEB_METRICS)
def test_web_metric_has_metrics(metric_name: str) -> None:
    assert has_metrics(
        query(MIMIR_UID, "prometheus", {"expr": metric_name, "instant": True})
    )
