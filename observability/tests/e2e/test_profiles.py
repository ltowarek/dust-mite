from typing import Any

import pytest

from tests.helpers.producers import PROFILE_TYPE
from tests.helpers.query import (
    PYROSCOPE_UID,
    has_profile_samples,
    query,
    wait_for_profile_samples,
)

_CAR_PROFILING_REASON = (
    "requires firmware built with sdkconfig.defaults.profiling, real ESP32 "
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
