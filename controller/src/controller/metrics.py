"""OpenTelemetry metrics configuration and pipeline-health recording."""

import logging
import os
from types import SimpleNamespace

import opentelemetry.metrics as otel_metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

logger = logging.getLogger(__name__)

_metrics: SimpleNamespace = SimpleNamespace(
    frames_processed=None,
    telemetry_packets_received=None,
    commands_sent=None,
)


def configure_metrics(service_name: str, provider: MeterProvider | None = None) -> None:
    """Configure OpenTelemetry metrics instruments.

    When ``provider`` is omitted, builds a production ``MeterProvider`` with
    OTLP/HTTP export and sets it as the global provider. Reads
    ``OTEL_EXPORTER_OTLP_METRICS_ENDPOINT`` from the environment in that case
    (raises ``KeyError`` if not set). Pass a ``MeterProvider`` explicitly to
    use a custom provider without touching the global state (useful in tests).
    """
    if provider is None:
        endpoint_url = os.environ["OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"]
        exporter = OTLPMetricExporter(endpoint=endpoint_url)
        reader = PeriodicExportingMetricReader(exporter, export_interval_millis=500)
        resource = Resource.create({SERVICE_NAME: service_name})
        provider = MeterProvider(resource=resource, metric_readers=[reader])
        otel_metrics.set_meter_provider(provider)

    meter = provider.get_meter(__name__)

    _metrics.frames_processed = meter.create_counter(
        "dust_mite.frames_processed",
        unit="{frame}",
        description="Number of camera frames processed",
    )
    _metrics.telemetry_packets_received = meter.create_counter(
        "dust_mite.telemetry_packets_received",
        unit="{packet}",
        description="Number of telemetry packets received from the car",
    )
    _metrics.commands_sent = meter.create_counter(
        "dust_mite.commands_sent",
        unit="{command}",
        description="Number of drive commands sent to the car",
    )


def record_frame() -> None:
    """Record one processed camera frame."""
    if _metrics.frames_processed is not None:
        _metrics.frames_processed.add(1)


def record_telemetry_received() -> None:
    """Record one received telemetry packet."""
    if _metrics.telemetry_packets_received is not None:
        _metrics.telemetry_packets_received.add(1)


def record_command_sent() -> None:
    """Record one drive command sent to the car."""
    if _metrics.commands_sent is not None:
        _metrics.commands_sent.add(1)
