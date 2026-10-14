"""OpenTelemetry metrics configuration and pipeline-health recording."""

import logging
from types import SimpleNamespace

import opentelemetry.metrics as otel_metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

from controller.command import Command

logger = logging.getLogger(__name__)

_metrics: SimpleNamespace = SimpleNamespace(
    frames_processed=None,
    telemetry_packets_received=None,
    commands_sent=None,
    commands_blocked=None,
)


def configure_metrics(endpoint: str | None, resource: Resource) -> None:
    """Export the pipeline-health metrics over OTLP/HTTP.

    Builds a ``MeterProvider`` exporting to ``endpoint``, the full metrics
    URL, sets it as the global provider and installs the instruments on it,
    skipping configuration if ``endpoint`` is empty.
    """
    if not endpoint:
        logger.debug("No OTLP metrics endpoint, skipping metrics configuration")
        return
    exporter = OTLPMetricExporter(endpoint=endpoint)
    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=500)
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    otel_metrics.set_meter_provider(provider)
    install_instruments(provider)


def install_instruments(provider: MeterProvider) -> None:
    """Create the pipeline-health instruments the `record_*` functions use."""
    meter = provider.get_meter(__name__)

    _metrics.frames_processed = meter.create_counter(
        "dust_mite_frames_processed",
        unit="{frame}",
        description="Number of camera frames processed",
    )
    _metrics.telemetry_packets_received = meter.create_counter(
        "dust_mite_telemetry_packets_received",
        unit="{packet}",
        description="Number of telemetry packets received from the car",
    )
    _metrics.commands_sent = meter.create_counter(
        "dust_mite_commands_sent",
        unit="{command}",
        description="Number of drive commands sent to the car",
    )
    _metrics.commands_blocked = meter.create_counter(
        "dust_mite_commands_blocked",
        unit="{command}",
        description="Number of drive commands the collision monitor replaced",
    )


def record_frame() -> None:
    """Record one processed camera frame."""
    if _metrics.frames_processed is not None:
        _metrics.frames_processed.add(1)


def record_telemetry_received() -> None:
    """Record one received telemetry packet."""
    if _metrics.telemetry_packets_received is not None:
        _metrics.telemetry_packets_received.add(1)


def record_command_sent(command: Command) -> None:
    """Record one drive command sent to the car, attributed by command name."""
    if _metrics.commands_sent is not None:
        _metrics.commands_sent.add(1, {"command.name": command.name})


def record_command_blocked(command: Command) -> None:
    """Record one drive command the collision monitor replaced, by its name."""
    if _metrics.commands_blocked is not None:
        _metrics.commands_blocked.add(1, {"command.name": command.name})
