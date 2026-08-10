"""Synthetic OTLP producers for pipeline-plumbing verification."""

import os
import time

import requests
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.proto.collector.profiles.v1development import (
    profiles_service_pb2,
)
from opentelemetry.proto.common.v1 import common_pb2
from opentelemetry.proto.profiles.v1development import profiles_pb2
from opentelemetry.proto.resource.v1 import resource_pb2
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind

_PROFILES_PATH = "/v1development/profiles"

# Long enough that force_flush (not the periodic timer) drives the export in a test.
_METRIC_EXPORT_INTERVAL_MILLIS = 60_000

# Matches the sample_type/period_type built from push_profile's own string_table
# below ("samples"/"count" for both value and period): Pyroscope's profileTypeId
# is "<sample_type>:<sample_unit>:<period_type>:<period_unit>". Defined once here,
# next to the producer that determines it, so tests/integration and tests/e2e
# can't drift from what push_profile actually emits.
PROFILE_TYPE = "samples:samples:count:samples:count"


def push_metric(
    endpoint: str, service_name: str, metric_name: str, value: float
) -> None:
    """Emit one synthetic counter value via the real OTel SDK, force-flushed now."""
    resource = Resource.create({SERVICE_NAME: service_name})
    exporter = OTLPMetricExporter(endpoint=endpoint)
    reader = PeriodicExportingMetricReader(
        exporter, export_interval_millis=_METRIC_EXPORT_INTERVAL_MILLIS
    )
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    counter = provider.get_meter(service_name).create_counter(metric_name)
    counter.add(value)
    provider.force_flush()
    provider.shutdown()


def push_span(endpoint: str, service_name: str, span_name: str) -> None:
    """Emit one synthetic span via the real OTel SDK, force-flushed immediately."""
    resource = Resource.create({SERVICE_NAME: service_name})
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    tracer = provider.get_tracer(service_name)
    with tracer.start_as_current_span(span_name, kind=SpanKind.INTERNAL):
        pass
    provider.force_flush()
    provider.shutdown()


def push_profile(endpoint: str, service_name: str) -> None:
    """POST one minimal, valid synthetic OTLP profile directly.

    No OTel SDK support exists for this signal, so this builds the protobuf
    request directly -- deliberately minimal (one sample, one stack frame),
    since the goal is proving the pipeline plumbing works, not faithfully
    replicating production payload shape.
    """
    strings = ["", "main", "test.py", "samples", "count"]
    dictionary = profiles_pb2.ProfilesDictionary(
        mapping_table=[profiles_pb2.Mapping(filename_strindex=0)],
        location_table=[
            profiles_pb2.Location(lines=[profiles_pb2.Line(function_index=0, line=1)])
        ],
        function_table=[profiles_pb2.Function(name_strindex=1, filename_strindex=2)],
        string_table=strings,
        stack_table=[profiles_pb2.Stack(location_indices=[0])],
    )
    value_type = profiles_pb2.ValueType(type_strindex=3, unit_strindex=4)
    profile = profiles_pb2.Profile(
        sample_type=value_type,
        samples=[profiles_pb2.Sample(stack_index=0, values=[1])],
        time_unix_nano=time.time_ns(),
        duration_nano=1_000_000_000,
        period_type=value_type,
        period=1,
        profile_id=os.urandom(16),
    )
    resource = resource_pb2.Resource(
        attributes=[
            common_pb2.KeyValue(
                key="service.name", value=common_pb2.AnyValue(string_value=service_name)
            )
        ]
    )
    request = profiles_service_pb2.ExportProfilesServiceRequest(
        resource_profiles=[
            profiles_pb2.ResourceProfiles(
                resource=resource,
                scope_profiles=[profiles_pb2.ScopeProfiles(profiles=[profile])],
            )
        ],
        dictionary=dictionary,
    )
    response = requests.post(
        endpoint.rstrip("/") + _PROFILES_PATH,
        data=request.SerializeToString(),
        headers={"Content-Type": "application/x-protobuf"},
        timeout=10,
    )
    response.raise_for_status()
