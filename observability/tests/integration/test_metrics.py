import os

from tests.helpers.producers import push_metric
from tests.helpers.query import MIMIR_UID, has_metrics, wait_for_metrics

_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318")
_MIMIR_METRICS_ENDPOINT = os.getenv(
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
    "http://mimir:8080/otlp/v1/metrics",
)


def test_direct_to_mimir_metric_is_queryable() -> None:
    """Car/streamer push metrics direct to Mimir, bypassing the collector."""
    metric_name = "dust_mite_synthetic_test_direct"
    push_metric(_MIMIR_METRICS_ENDPOINT, "dust-mite-synthetic", metric_name, 1)

    result = wait_for_metrics(
        MIMIR_UID, "prometheus", {"expr": metric_name, "instant": True}
    )

    assert has_metrics(result)


def test_metric_through_collector_is_queryable() -> None:
    """Web metrics go through the Collector, unlike car/streamer's direct path."""
    metric_name = "dust_mite_synthetic_test_via_collector"
    push_metric(f"{_OTLP_ENDPOINT}/v1/metrics", "dust-mite-synthetic", metric_name, 1)

    result = wait_for_metrics(
        MIMIR_UID, "prometheus", {"expr": metric_name, "instant": True}
    )

    assert has_metrics(result)
