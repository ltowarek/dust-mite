import sys
import time

import pytest
from opentelemetry.proto.collector.profiles.v1development import (
    profiles_service_pb2,
)
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

import otlp_profiler

from .test_doubles import CollectorServer

_EXPORT_INTERVAL_MS = 50
_WAIT_TIMEOUT_S = 10


@pytest.mark.skipif(sys.platform != "linux", reason="on-CPU filtering is Linux-only")
def test_exports_profiles_of_the_given_resource(collector: CollectorServer) -> None:
    sampler = otlp_profiler.configure(
        collector.profiles_endpoint,
        Resource({SERVICE_NAME: "configure-test"}),
        export_interval_ms=_EXPORT_INTERVAL_MS,
    )
    try:
        # Busy-wait: the sampler records only threads that are on the CPU, and
        # it exports nothing for an interval without samples.
        deadline = time.monotonic() + _WAIT_TIMEOUT_S
        while not collector.received and time.monotonic() < deadline:
            pass
    finally:
        sampler.stop()

    request = profiles_service_pb2.ExportProfilesServiceRequest.FromString(
        collector.received[0].body
    )
    resource = request.resource_profiles[0].resource
    assert {kv.key: kv.value.string_value for kv in resource.attributes} == {
        SERVICE_NAME: "configure-test"
    }
