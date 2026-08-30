import pytest

from tests.helpers.query import (
    LOKI_UID,
    has_logs,
    logql_attribute_query,
    logql_query,
    logql_severity_query,
    query,
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
