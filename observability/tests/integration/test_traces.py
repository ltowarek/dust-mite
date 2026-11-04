import pytest

from tests.helpers.producers import push_span
from tests.helpers.query import TEMPO_UID, has_traces, traceql_query, wait_for_traces
from tests.helpers.settings import STACK_SETTINGS


@pytest.mark.parametrize(
    "service_name", ["dust-mite-car", "dust-mite-streamer", "dust-mite-web"]
)
def test_synthetic_span_is_queryable(service_name: str) -> None:
    """All three services export traces through the same OTel Collector path."""
    span_name = "test.synthetic.span"
    push_span(f"{STACK_SETTINGS.otlp_endpoint}/v1/traces", service_name, span_name)

    result = wait_for_traces(TEMPO_UID, "tempo", traceql_query(service_name, span_name))

    assert has_traces(result)
