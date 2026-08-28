import os

from tests.helpers.producers import push_log
from tests.helpers.query import LOKI_UID, has_logs, logql_query, wait_for_logs

_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318")


def test_synthetic_log_is_queryable() -> None:
    """No real component emits logs yet -- this only proves the pipeline plumbing."""
    service_name = "dust-mite-synthetic"
    log_body = "test synthetic log"
    push_log(f"{_OTLP_ENDPOINT}/v1/logs", service_name, log_body)

    result = wait_for_logs(LOKI_UID, "loki", logql_query(service_name, log_body))

    assert has_logs(result)
