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
    "dust_mite_task_stack_min_free_bytes",
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
    "dust_mite_camera_frames_captured",
    "dust_mite_camera_frame_size_bytes",
    "dust_mite_camera_frame_buffer_bytes",
    "dust_mite_camera_frames_sent",
]
STREAMER_METRICS = [
    "dust_mite_camera_frames_processed",
    "dust_mite_telemetry_messages_received",
    "dust_mite_commands_sent",
    "dust_mite_viewer_camera_frames_sent",
]


class TestMetricPipeline:
    @pytest.mark.dut
    @pytest.mark.parametrize(
        "metric_name",
        [pytest.param(name, id=f"car exports {name}") for name in CAR_METRICS]
        + [
            pytest.param(name, id=f"streamer exports {name}")
            for name in STREAMER_METRICS
        ],
    )
    def test_service_metric_has_metrics(self, metric_name: str) -> None:
        assert has_metrics(
            query(MIMIR_UID, "prometheus", {"expr": metric_name, "instant": True})
        )
