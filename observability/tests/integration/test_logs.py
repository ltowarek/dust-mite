import os

import pytest

from tests.helpers.producers import push_log
from tests.helpers.query import (
    LOKI_UID,
    has_logs,
    logql_attribute_query,
    logql_query,
    wait_for_logs,
)

_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318")

_SOURCE_LINK_SERVICE_NAME = "dust-mite-source-link-log-test"
_SOURCE_LINK_ATTRIBUTES = {
    "vcs.repository.url.full": "https://github.com/ltowarek/dust-mite",
    "vcs.ref.head.revision": "abc123",
}


def test_synthetic_log_is_queryable() -> None:
    """Proves the pipeline plumbing works; tests/e2e/ covers real components."""
    service_name = "dust-mite-synthetic"
    log_body = "test synthetic log"
    push_log(f"{_OTLP_ENDPOINT}/v1/logs", service_name, log_body)

    result = wait_for_logs(LOKI_UID, "loki", logql_query(service_name, log_body))

    assert has_logs(result)


@pytest.fixture(scope="module", autouse=True)
def _pushed_source_link_log() -> None:
    push_log(
        f"{_OTLP_ENDPOINT}/v1/logs",
        _SOURCE_LINK_SERVICE_NAME,
        "vcs source link probe",
        _SOURCE_LINK_ATTRIBUTES,
    )


@pytest.mark.parametrize("attribute_key", sorted(_SOURCE_LINK_ATTRIBUTES))
def test_github_source_link_attribute_is_queryable(attribute_key: str) -> None:
    """GitHub source linking requires this attribute to be queryable."""
    loki_key = attribute_key.replace(".", "_")
    value = _SOURCE_LINK_ATTRIBUTES[attribute_key]
    result = wait_for_logs(
        LOKI_UID,
        "loki",
        logql_attribute_query(_SOURCE_LINK_SERVICE_NAME, loki_key, value),
    )

    assert has_logs(result)
