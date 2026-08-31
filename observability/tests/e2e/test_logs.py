import pytest

from tests.helpers.query import (
    LOKI_UID,
    TEMPO_UID,
    has_logs,
    has_traces,
    log_label_values,
    logql_attribute_query,
    logql_query,
    logql_severity_query,
    query,
    trace_id_query,
    wait_for_traces,
)

CASES: list[tuple[str, str]] = [
    ("dust-mite-streamer", "Starting server"),
    ("dust-mite-controller", "Sending new command with value"),
    ("dust-mite-web", "dust-mite-web logging initialized"),
    ("dust-mite-car", "Starting camera task"),
]


@pytest.mark.dut
@pytest.mark.parametrize(("service_name", "log_body"), CASES)
def test_service_has_recent_log(service_name: str, log_body: str) -> None:
    assert has_logs(query(LOKI_UID, "loki", logql_query(service_name, log_body)))


@pytest.mark.dut
def test_car_log_has_correct_severity() -> None:
    """Confirms car's logs reach Loki with severity intact, not just the body text."""
    result = query(
        LOKI_UID,
        "loki",
        logql_severity_query("dust-mite-car", "Starting camera task", "INFO"),
    )
    assert has_logs(result)


@pytest.mark.dut
def test_streamer_server_handler_log_resolves_to_a_real_trace() -> None:
    """Proves the correlation mechanism (see tests/integration/test_logs.py's
    synthetic version) holds for a real call site, not just synthetic data."""
    log_result = query(
        LOKI_UID,
        "loki",
        logql_query("dust-mite-streamer", "Server connection from"),
        time_range="now-1h",
    )
    trace_ids = log_label_values(log_result, "trace_id")
    assert trace_ids, "no streamer.server_handler connection logged in the last hour"

    resolved = next(
        (
            trace_id
            for trace_id in trace_ids
            if has_traces(
                wait_for_traces(
                    TEMPO_UID,
                    "tempo",
                    trace_id_query(trace_id),
                    time_range="now-1h",
                    timeout=10.0,
                )
            )
        ),
        None,
    )
    assert resolved is not None, (
        f"none of {len(trace_ids)} candidate connection(s) had a closed "
        "streamer.server_handler span in Tempo"
    )


@pytest.mark.dut
def test_car_log_has_source_link_attribute() -> None:
    """Confirms car's logs carry the GitHub source-linking resource attribute."""
    result = query(
        LOKI_UID,
        "loki",
        logql_attribute_query(
            "dust-mite-car",
            "vcs_repository_url_full",
            "https://github.com/ltowarek/dust-mite",
        ),
    )
    assert has_logs(result)
