import pytest
import requests
from opentelemetry.proto.collector.profiles.v1development import (
    profiles_service_pb2,
)
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

from otlp_profiler import exporter
from otlp_profiler.aggregator import SampleKey

from .test_doubles import PROFILES_PATH, CollectorServer

_STACK_A = (("main", "app.py", 10), ("busy", "app.py", 20))
_STACK_B = (("main", "app.py", 10),)


def _sample_counts() -> dict[SampleKey, int]:
    return {
        (_STACK_A, "MainThread", None): 3,
        (
            _STACK_B,
            "worker-1",
            (0x0102030405060708090A0B0C0D0E0F10, 0x1234ABCD5678EF90),
        ): 1,
    }


_SETTINGS = exporter.ProfileSettings(Resource({SERVICE_NAME: "svc"}), sample_rate=100)
_WINDOW = exporter.ProfileWindow(
    time_unix_nano=1_700_000_000_000_000_000, duration_nano=500_000_000
)


class TestExport:
    def test_does_nothing_when_counts_are_empty(
        self, collector: CollectorServer
    ) -> None:
        exporter.export({}, _SETTINGS, _WINDOW, collector.profiles_endpoint)

        assert collector.received == []

    def test_posts_protobuf_to_the_endpoint_as_given(
        self, collector: CollectorServer
    ) -> None:
        exporter.export(
            _sample_counts(), _SETTINGS, _WINDOW, collector.profiles_endpoint
        )

        assert len(collector.received) == 1
        request = collector.received[0]
        assert request.path == PROFILES_PATH
        assert request.headers["Content-Type"] == "application/x-protobuf"
        # raises if not a valid ExportProfilesServiceRequest
        profiles_service_pb2.ExportProfilesServiceRequest.FromString(request.body)

    def test_raises_when_collector_returns_an_error_status(
        self, collector: CollectorServer
    ) -> None:
        collector.response_status = 500

        with pytest.raises(requests.exceptions.HTTPError):
            exporter.export(
                _sample_counts(), _SETTINGS, _WINDOW, collector.profiles_endpoint
            )
