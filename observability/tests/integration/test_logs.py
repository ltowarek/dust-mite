import os

import pytest

from tests.helpers.producers import push_log, push_span_with_log
from tests.helpers.query import (
    LOKI_UID,
    TEMPO_UID,
    datasource_settings,
    has_logs,
    has_traces,
    logql_attribute_query,
    logql_query,
    trace_id_query,
    wait_for_logs,
    wait_for_traces,
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


def test_log_inside_a_span_resolves_to_that_trace() -> None:
    """A log emitted inside an open span carries its trace ID back to a real trace."""
    service_name = "dust-mite-trace-log-correlation"
    span_name = "test.synthetic.span.with.log"
    log_body = "test synthetic log inside span"
    trace_id = push_span_with_log(
        f"{_OTLP_ENDPOINT}/v1/traces",
        f"{_OTLP_ENDPOINT}/v1/logs",
        service_name,
        span_name,
        log_body,
    )

    log_result = wait_for_logs(
        LOKI_UID, "loki", logql_attribute_query(service_name, "trace_id", trace_id)
    )
    assert has_logs(log_result)

    trace_result = wait_for_traces(TEMPO_UID, "tempo", trace_id_query(trace_id))
    assert has_traces(trace_result)


def test_tempo_datasource_has_traces_to_logs_v2() -> None:
    """The Tempo datasource has a tracesToLogsV2 block pointing at Loki by trace ID."""
    settings = datasource_settings(TEMPO_UID)
    traces_to_logs = settings["jsonData"]["tracesToLogsV2"]
    assert traces_to_logs["datasourceUid"] == LOKI_UID
    assert traces_to_logs["filterByTraceID"] is True
    assert {"key": "service.name", "value": "service_name"} in traces_to_logs["tags"]


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
