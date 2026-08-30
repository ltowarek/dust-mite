"""Shared helper for querying Grafana's real `/api/ds/query` endpoint.

Every panel/Explore query Grafana's UI issues goes through this one HTTP
endpoint. Querying it directly with the same payload a real panel would
build is the most reliable way to verify "would this actually display data"
without a browser.
"""

import os
import time
from collections.abc import Callable
from typing import Any, cast

import requests

TEMPO_UID = "tempo"
PYROSCOPE_UID = "pyroscope"
MIMIR_UID = "mimir"
LOKI_UID = "loki"

_PROFILE_TOTAL_ROW = (
    1  # an empty flame graph still returns one row -- see has_profile_samples
)


def grafana_url() -> str:
    """Return the base URL of the Grafana instance to query."""
    return os.getenv("GRAFANA_URL", "http://localhost:3000")


def query(
    datasource_uid: str,
    datasource_type: str,
    fields: dict[str, Any],
    *,
    time_range: str = "now-5m",
) -> dict[str, Any]:
    """POST one query to `/api/ds/query` exactly as a real panel would.

    Returns the response for `refId` "A" -- callers only ever issue one query
    per request, so there is never a second result to disambiguate.
    """
    response = requests.post(
        f"{grafana_url()}/api/ds/query",
        json={
            "queries": [
                {
                    "refId": "A",
                    "datasource": {"type": datasource_type, "uid": datasource_uid},
                    **fields,
                }
            ],
            "from": time_range,
            "to": "now",
        },
        timeout=10,
    )
    response.raise_for_status()
    return cast("dict[str, Any]", response.json()["results"]["A"])


def traceql_query(service_name: str, span_name: str) -> dict[str, Any]:
    """Build the `/api/ds/query` payload fields for a TraceQL lookup.

    Shared by `tests/integration/test_traces.py` and `tests/e2e/test_traces.py`
    so the query shape can't drift between the two suites.
    """
    return {
        "queryType": "traceql",
        "query": f'{{resource.service.name="{service_name}" && name="{span_name}"}}',
        "limit": 20,
        "tableType": "traces",
    }


def logql_query(service_name: str, log_body: str) -> dict[str, Any]:
    """Build the `/api/ds/query` payload fields for a LogQL lookup."""
    return {
        "queryType": "range",
        "expr": f'{{service_name="{service_name}"}} |= `{log_body}`',
    }


def logql_severity_query(
    service_name: str, log_body: str, severity_text: str
) -> dict[str, Any]:
    """Build the `/api/ds/query` payload fields for a severity-filtered LogQL lookup.

    `logql_query` alone proves a log line exists; this additionally proves it
    was ingested with the severity the call site actually used, not just any
    severity.
    """
    selector = f'{{service_name="{service_name}"}}'
    return {
        "queryType": "range",
        "expr": f"{selector} |= `{log_body}` | severity_text=`{severity_text}`",
    }


def logql_attribute_query(
    service_name: str, attribute_key: str, attribute_value: str
) -> dict[str, Any]:
    """Build the `/api/ds/query` payload fields for a structured-metadata lookup.

    OTel resource attributes other than `service.name` land in Loki as
    structured metadata, not stream labels -- `{service_name="..."}` alone
    can't select on them, but a `| key=value` label filter expression can.
    `attribute_key` must already be in Loki's dot-to-underscore form (e.g.
    `vcs_repository_url_full`).
    """
    selector = f'{{service_name="{service_name}"}}'
    return {
        "queryType": "range",
        "expr": f"{selector} | {attribute_key}=`{attribute_value}`",
    }


def _has_any_rows(result: dict[str, Any]) -> bool:
    """True if any frame has at least one row.

    An empty match returns either zero frames or a frame with zero-length
    columns, for Prometheus (timeseries), Tempo (traceql table), and Loki
    (logql range) responses alike. Profiles behave differently -- see
    `has_profile_samples`.
    """
    for frame in result.get("frames", []):
        values = frame.get("data", {}).get("values", [])
        if values and len(values[0]) > 0:
            return True
    return False


def has_metrics(result: dict[str, Any]) -> bool:
    """True if a Prometheus query result has any rows."""
    return _has_any_rows(result)


def has_traces(result: dict[str, Any]) -> bool:
    """True if a Tempo TraceQL query result has any rows."""
    return _has_any_rows(result)


def has_logs(result: dict[str, Any]) -> bool:
    """True if a Loki LogQL query result has any rows."""
    return _has_any_rows(result)


def has_profile_samples(result: dict[str, Any]) -> bool:
    """Profiles: an empty flame graph is NOT zero rows.

    A query with no matching samples still returns one row -- a synthetic
    "total" root node with value=0 (level/value/self/label columns). A bare
    "any rows?" check would wrongly report data present, so this requires
    more than just that placeholder row, or a nonzero total value.

    Looks up the "value" column by its schema field name rather than a fixed
    index -- this response shape has already changed once between Grafana
    versions, so column order isn't assumed stable across versions either.
    """
    for frame in result.get("frames", []):
        values = frame.get("data", {}).get("values", [])
        if not values:
            continue
        row_count = len(values[0])
        if row_count > _PROFILE_TOTAL_ROW:
            return True
        fields = frame.get("schema", {}).get("fields", [])
        value_col = next(
            (i for i, f in enumerate(fields) if f["name"] == "value"), None
        )
        if (
            row_count == _PROFILE_TOTAL_ROW
            and value_col is not None
            and values[value_col][0] > 0
        ):
            return True
    return False


def _wait_for(  # noqa: PLR0913 -- each param independently configures the poll
    is_ready: Callable[[dict[str, Any]], bool],
    datasource_uid: str,
    datasource_type: str,
    fields: dict[str, Any],
    *,
    time_range: str,
    timeout: float,
    interval: float,
) -> dict[str, Any]:
    """Poll `query(...)` until `is_ready(result)` is true or `timeout` elapses.

    A datasource that isn't accepting queries yet (e.g. Grafana reports
    healthy before a backend it proxies to has finished starting) raises
    instead of returning an empty result, so that's retried too, unless the
    deadline has already passed, in which case the error is the most useful
    thing to surface.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            result = query(
                datasource_uid, datasource_type, fields, time_range=time_range
            )
        except requests.RequestException:
            if time.monotonic() >= deadline:
                raise
            time.sleep(interval)
            continue
        if is_ready(result) or time.monotonic() >= deadline:
            return result
        time.sleep(interval)


def wait_for_metrics(  # noqa: PLR0913 -- each param independently configures the poll
    datasource_uid: str,
    datasource_type: str,
    fields: dict[str, Any],
    *,
    time_range: str = "now-5m",
    timeout: float = 60.0,
    interval: float = 2.0,
) -> dict[str, Any]:
    """Poll until a metrics query result has data, or `timeout` elapses."""
    return _wait_for(
        has_metrics,
        datasource_uid,
        datasource_type,
        fields,
        time_range=time_range,
        timeout=timeout,
        interval=interval,
    )


def wait_for_traces(  # noqa: PLR0913 -- each param independently configures the poll
    datasource_uid: str,
    datasource_type: str,
    fields: dict[str, Any],
    *,
    time_range: str = "now-5m",
    timeout: float = 60.0,
    interval: float = 2.0,
) -> dict[str, Any]:
    """Poll until a traces query result has data, or `timeout` elapses.

    A single freshly-pushed span is not queryable instantly: Tempo takes
    roughly 5-30s to index a brand-new block, varying with its own
    flush/indexing cycle rather than request latency. An already-flowing,
    minutes-old stream (what the e2e suite checks) looks instant by
    comparison, but a synthetic single-sample push races this indexing delay
    every time, hence polling with a safety margin instead of querying once.
    """
    return _wait_for(
        has_traces,
        datasource_uid,
        datasource_type,
        fields,
        time_range=time_range,
        timeout=timeout,
        interval=interval,
    )


def wait_for_logs(  # noqa: PLR0913 -- each param independently configures the poll
    datasource_uid: str,
    datasource_type: str,
    fields: dict[str, Any],
    *,
    time_range: str = "now-5m",
    timeout: float = 60.0,
    interval: float = 2.0,
) -> dict[str, Any]:
    """Poll until a logs query result has data, or `timeout` elapses."""
    return _wait_for(
        has_logs,
        datasource_uid,
        datasource_type,
        fields,
        time_range=time_range,
        timeout=timeout,
        interval=interval,
    )


def wait_for_profile_samples(  # noqa: PLR0913 -- each param independently configures the poll
    datasource_uid: str,
    datasource_type: str,
    fields: dict[str, Any],
    *,
    time_range: str = "now-2h",
    timeout: float = 300.0,
    interval: float = 5.0,
) -> dict[str, Any]:
    """Poll until samples appear or `timeout` elapses.

    Pyroscope's ingestion lag varies with load: ~30-40s when idle, but
    several tests pushing profiles back to back (e.g. in CI) can push a
    given push's lag past 150s -- 300s leaves real margin above the worst
    case actually seen, not just the typical one.
    """
    return _wait_for(
        has_profile_samples,
        datasource_uid,
        datasource_type,
        fields,
        time_range=time_range,
        timeout=timeout,
        interval=interval,
    )
