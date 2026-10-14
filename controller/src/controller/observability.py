"""Observability settings and the setup every entry point shares."""

import dataclasses
from collections.abc import Mapping
from typing import Self

from .logging import configure_logging
from .metrics import configure_metrics
from .otel import service_resource
from .profiling import configure_profiling
from .tracing import configure_tracing


@dataclasses.dataclass(frozen=True)
class ObservabilitySettings:
    """OpenTelemetry export settings, read from the environment."""

    otlp_endpoint: str | None
    metrics_endpoint: str | None
    repository: str | None
    profiling_enabled: bool

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> Self:
        """Read the settings from `environ`, leaving unset ones disabled."""
        return cls(
            otlp_endpoint=environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
            metrics_endpoint=environ.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"),
            repository=environ.get("SERVICE_REPOSITORY"),
            profiling_enabled=environ.get("PROFILING_ENABLED") == "1",
        )


def configure_observability(service_name: str, settings: ObservabilitySettings) -> None:
    """Configure tracing, logging, metrics and profiling for `service_name`."""
    resource = service_resource(service_name, settings.repository)
    configure_tracing(settings.otlp_endpoint, resource)
    configure_logging(settings.otlp_endpoint, resource)
    configure_metrics(settings.metrics_endpoint, resource)
    configure_profiling(
        service_name,
        settings.otlp_endpoint,
        settings.repository,
        enabled=settings.profiling_enabled,
    )
