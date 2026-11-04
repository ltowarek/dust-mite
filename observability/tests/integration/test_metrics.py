from tests.helpers.producers import push_metric
from tests.helpers.query import MIMIR_UID, has_metrics, wait_for_metrics
from tests.helpers.settings import STACK_SETTINGS


def test_direct_to_mimir_metric_is_queryable() -> None:
    """Car/streamer/web all push metrics direct to Mimir, bypassing the collector."""
    metric_name = "dust_mite_synthetic_test_direct"
    push_metric(STACK_SETTINGS.metrics_endpoint, "dust-mite-synthetic", metric_name, 1)

    result = wait_for_metrics(
        MIMIR_UID, "prometheus", {"expr": metric_name, "instant": True}
    )

    assert has_metrics(result)
