import pytest

from tests.helpers.query import VICTORIAMETRICS_UID, has_metrics, query

CAR_METRICS = [
    "dust_mite.free_heap_bytes",
    "dust_mite.min_free_heap_bytes",
    "dust_mite.largest_free_block_bytes",
    "dust_mite.internal_free_heap_bytes",
    "dust_mite.free_psram_bytes",
    "dust_mite.uptime",
    "dust_mite.temperature",
    "dust_mite.task_cpu_usage",
    "dust_mite.task_priority",
    "dust_mite.rssi",
    "dust_mite.speed",
    "dust_mite.distance_ahead",
    "dust_mite.accelerometer.x",
    "dust_mite.accelerometer.y",
    "dust_mite.accelerometer.z",
    "dust_mite.magnetometer.x",
    "dust_mite.magnetometer.y",
    "dust_mite.magnetometer.z",
    "dust_mite.gyroscope.x",
    "dust_mite.gyroscope.y",
    "dust_mite.gyroscope.z",
    "dust_mite.frames_captured",
    "dust_mite.camera.frame_size_bytes",
    "dust_mite.camera.frame_buffer_bytes",
    "dust_mite.frames_sent",
]
STREAMER_METRICS = [
    "dust_mite.frames_processed",
    "dust_mite.telemetry_packets_received",
    "dust_mite.commands_sent",
]
WEB_METRICS = ["dust_mite.frames_displayed"]


@pytest.mark.dut
@pytest.mark.parametrize("metric_name", CAR_METRICS)
def test_car_metric_has_metrics(metric_name: str) -> None:
    assert has_metrics(
        query(VICTORIAMETRICS_UID, "prometheus", {"expr": metric_name, "instant": True})
    )


@pytest.mark.dut
@pytest.mark.parametrize("metric_name", STREAMER_METRICS)
def test_streamer_metric_has_metrics(metric_name: str) -> None:
    assert has_metrics(
        query(VICTORIAMETRICS_UID, "prometheus", {"expr": metric_name, "instant": True})
    )


@pytest.mark.dut
@pytest.mark.parametrize("metric_name", WEB_METRICS)
def test_web_metric_has_metrics(metric_name: str) -> None:
    assert has_metrics(
        query(VICTORIAMETRICS_UID, "prometheus", {"expr": metric_name, "instant": True})
    )
