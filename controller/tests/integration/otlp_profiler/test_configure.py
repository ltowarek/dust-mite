import logging
import sys
import time
from collections.abc import Callable

import pytest
from opentelemetry.proto.collector.profiles.v1development import (
    profiles_service_pb2,
)
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

import otlp_profiler

from .test_doubles import CollectorServer

_EXPORT_INTERVAL_MS = 50
_WAIT_TIMEOUT_S = 10
_RESOURCE = Resource({SERVICE_NAME: "configure-test"})

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="on-CPU filtering is Linux-only"
)


def _profile_until(collector: CollectorServer, condition: Callable[[], bool]) -> None:
    """Run the profiler against `collector`, keeping the CPU busy until `condition`.

    The sampler records only threads that are on the CPU, and it exports
    nothing for an interval without samples, so this thread busy-waits.
    """
    sampler = otlp_profiler.configure(
        collector.profiles_endpoint, _RESOURCE, export_interval_ms=_EXPORT_INTERVAL_MS
    )
    try:
        deadline = time.monotonic() + _WAIT_TIMEOUT_S
        while not condition() and time.monotonic() < deadline:
            pass
    finally:
        sampler.stop()


def test_exports_profiles_of_the_given_resource(collector: CollectorServer) -> None:
    _profile_until(collector, lambda: bool(collector.received))

    request = profiles_service_pb2.ExportProfilesServiceRequest.FromString(
        collector.received[0].body
    )
    resource = request.resource_profiles[0].resource
    assert {kv.key: kv.value.string_value for kv in resource.attributes} == {
        SERVICE_NAME: "configure-test"
    }


def test_logs_a_failed_export(
    collector: CollectorServer, caplog: pytest.LogCaptureFixture
) -> None:
    collector.response_status = 500

    with caplog.at_level(logging.ERROR, logger="otlp_profiler"):
        _profile_until(
            collector, lambda: "failed to export profiles" in caplog.messages
        )

    assert "failed to export profiles" in caplog.messages
