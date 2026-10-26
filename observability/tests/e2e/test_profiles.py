from typing import Any

import pytest

from tests.helpers.producers import PROFILE_TYPE
from tests.helpers.query import (
    PYROSCOPE_UID,
    TEMPO_UID,
    Poll,
    has_profile_samples,
    query,
    span_ids,
    traceql_spans_query,
    wait_for_profile_samples,
    wait_for_traces,
)

_CAR_PROFILING_REASON = (
    "requires firmware built with sdkconfig.defaults.debug, real ESP32 "
    "hardware, and the profiling-symbolizer container"
)
_STREAMER_PROFILING_REASON = "requires PROFILING_ENABLED=1 on the streamer"


def _profile_query(service_name: str) -> dict[str, Any]:
    return {
        "queryType": "profile",
        "profileTypeId": PROFILE_TYPE,
        "labelSelector": f'{{service_name="{service_name}"}}',
    }


@pytest.mark.dut(reason=_CAR_PROFILING_REASON)
def test_car_has_profile_samples() -> None:
    result = wait_for_profile_samples(
        PYROSCOPE_UID, "grafana-pyroscope-datasource", _profile_query("dust-mite-car")
    )
    assert has_profile_samples(result)


@pytest.mark.dut(reason=_STREAMER_PROFILING_REASON)
def test_streamer_has_profile_samples() -> None:
    result = wait_for_profile_samples(
        PYROSCOPE_UID,
        "grafana-pyroscope-datasource",
        _profile_query("dust-mite-streamer"),
    )
    assert has_profile_samples(result)


@pytest.mark.dut(reason=_STREAMER_PROFILING_REASON)
def test_streamer_span_has_linked_profile_samples() -> None:
    """Many spans are selected at once: a single short span often catches no sample."""
    spans = span_ids(
        wait_for_traces(
            TEMPO_UID,
            "tempo",
            traceql_spans_query("dust-mite-streamer", "streamer.process_camera_frame"),
            Poll(time_range="now-15m"),
        )
    )
    # An empty span selector matches every sample, so the check needs spans.
    assert spans, "no streamer.process_camera_frame span in the last 15 minutes"

    result = wait_for_profile_samples(
        PYROSCOPE_UID,
        "grafana-pyroscope-datasource",
        {**_profile_query("dust-mite-streamer"), "spanSelector": spans},
    )
    assert has_profile_samples(result)


@pytest.mark.dut
def test_web_has_no_profile_samples() -> None:
    """dust-mite-web has no profiling instrumentation at all (browsers can't be
    CPU-sampled this way) -- asserted explicitly so this suite documents the
    gap as a permanent regression guard rather than a silent omission. If this
    starts failing (samples appear), someone added browser profiling: promote
    this to a real presence test and update docs/variants/copper.md.
    """
    result = query(
        PYROSCOPE_UID,
        "grafana-pyroscope-datasource",
        _profile_query("dust-mite-web"),
        time_range="now-2h",
    )
    assert not has_profile_samples(result)
