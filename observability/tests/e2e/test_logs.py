import pytest

from tests.helpers.query import LOKI_UID, has_logs, logql_query, query

# No real component emits logs yet.
CASES: list[tuple[str, str]] = []


@pytest.mark.dut
@pytest.mark.parametrize(("service_name", "log_body"), CASES)
def test_service_has_recent_log(service_name: str, log_body: str) -> None:
    assert has_logs(query(LOKI_UID, "loki", logql_query(service_name, log_body)))
