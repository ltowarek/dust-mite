import os

import pytest

from tests.helpers.producers import PROFILE_TYPE, push_profile
from tests.helpers.query import (
    PYROSCOPE_UID,
    has_profile_samples,
    wait_for_profile_samples,
)

_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318")

_SERVICE_NAMES = ["dust-mite-car", "dust-mite-streamer"]


@pytest.fixture(scope="module", autouse=True)
def _pushed_profiles() -> None:
    """Push every synthetic profile before any test polls for one.

    Pushing them all up front lets their ingestion lag overlap. Pushing one
    per test case instead would serialize that lag: whichever service's test
    runs first pays it alone, then times out even though the sample lands a
    few seconds after that test gives up -- this was observed consistently
    for the first parametrized case regardless of which service it was.
    """
    for service_name in _SERVICE_NAMES:
        push_profile(_OTLP_ENDPOINT, service_name)


@pytest.mark.parametrize("service_name", _SERVICE_NAMES)
def test_synthetic_profile_is_queryable(service_name: str) -> None:
    """Only car and streamer support profiling; web has no profiling instrumentation."""
    result = wait_for_profile_samples(
        PYROSCOPE_UID,
        "grafana-pyroscope-datasource",
        {
            "queryType": "profile",
            "profileTypeId": PROFILE_TYPE,
            "labelSelector": f'{{service_name="{service_name}"}}',
        },
    )

    assert has_profile_samples(result)
