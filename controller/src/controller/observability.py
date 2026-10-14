"""Observability settings and the setup every entry point shares."""

import dataclasses
import logging
from collections.abc import Mapping
from typing import Self

from .logging import configure_logging
from .metrics import configure_metrics
from .otel import service_resource
from .profiling import configure_profiling
from .tracing import configure_tracing

logger = logging.getLogger(__name__)

# The profiles signal is still in development, so the pinned collector serves
# it under the development version rather than `v1`.
_PROFILES_PATH = "v1development/profiles"


def _signal_endpoint(
    environ: Mapping[str, str], signal_variable: str, path: str
) -> str | None:
    """Return a signal's OTLP/HTTP URL, as the OTLP exporter spec resolves it.

    The signal's own variable is used as given; otherwise `path` is appended
    to the shared base `OTEL_EXPORTER_OTLP_ENDPOINT`.
    """
    if endpoint := environ.get(signal_variable):
        return endpoint
    if base := environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return f"{base.rstrip('/')}/{path}"
    return None


@dataclasses.dataclass(frozen=True)
class ObservabilitySettings:
    """OpenTelemetry export settings, read from the environment."""

    traces_endpoint: str | None
    logs_endpoint: str | None
    metrics_endpoint: str | None
    profiles_endpoint: str | None
    repository: str | None
    profiling_enabled: bool

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> Self:
        """Read the settings from `environ`, leaving unset ones disabled.

        Metrics have no fallback to the shared base endpoint: they go straight
        to Mimir, and the collector the base endpoint names has no metrics
        pipeline.
        """
        return cls(
            traces_endpoint=_signal_endpoint(
                environ, "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "v1/traces"
            ),
            logs_endpoint=_signal_endpoint(
                environ, "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "v1/logs"
            ),
            metrics_endpoint=environ.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"),
            profiles_endpoint=_signal_endpoint(
                environ, "OTEL_EXPORTER_OTLP_PROFILES_ENDPOINT", _PROFILES_PATH
            ),
            repository=environ.get("SERVICE_REPOSITORY"),
            profiling_enabled=environ.get("PROFILING_ENABLED") == "1",
        )


def configure_observability(service_name: str, settings: ObservabilitySettings) -> None:
    """Configure tracing, logging, metrics and profiling for `service_name`.

    Profiling is opt-in, unlike the other signals: it only starts if
    ``settings.profiling_enabled`` is true.
    """
    resource = service_resource(service_name, settings.repository)
    configure_tracing(settings.traces_endpoint, resource)
    configure_logging(settings.logs_endpoint, resource)
    configure_metrics(settings.metrics_endpoint, resource)
    if not settings.profiling_enabled:
        logger.debug("Profiling not enabled, skipping profiler configuration")
        return
    configure_profiling(service_name, settings.profiles_endpoint, settings.repository)
