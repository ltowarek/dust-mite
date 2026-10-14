"""Observability settings and the setup every entry point shares."""

import dataclasses
from collections.abc import Mapping
from typing import Self

from .logging import configure_logging
from .metrics import configure_metrics
from .tracing import configure_tracing


@dataclasses.dataclass(frozen=True)
class ObservabilitySettings:
    """OpenTelemetry export settings, read from the environment."""

    otlp_endpoint: str | None
    metrics_endpoint: str | None
    repository: str
    profiling_enabled: bool

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> Self:
        """Read the settings from `environ`, leaving unset ones disabled."""
        return cls(
            otlp_endpoint=environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
            metrics_endpoint=environ.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"),
            repository=environ.get("SERVICE_REPOSITORY", ""),
            profiling_enabled=environ.get("PROFILING_ENABLED") == "1",
        )


def configure_observability(service_name: str, settings: ObservabilitySettings) -> None:
    """Configure tracing, logging and metrics for `service_name`.

    Profiling is left to the caller: only the streamer runs long enough
    for it to be worth sampling.
    """
    configure_tracing(service_name, settings.otlp_endpoint, settings.repository)
    configure_logging(service_name, settings.otlp_endpoint, settings.repository)
    configure_metrics(service_name, settings.metrics_endpoint, settings.repository)
