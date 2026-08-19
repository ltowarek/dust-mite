"""Dust-mite-specific wiring for the generic `otlp_profiler` package."""

import logging
import os

import otlp_profiler
from controller.otel import current_repository, resolve_current_git_ref

logger = logging.getLogger(__name__)

_ENABLED_VALUE = "1"
_ROOT_PATH = "controller"


def resolve_endpoint(profiling_enabled: str, endpoint: str | None) -> str | None:
    """Return the endpoint to profile with, or None if profiling should stay off.

    Pure decision logic factored out of `configure_profiling` so it can be
    tested directly with plain string arguments, without needing environment
    variables or a fake `otlp_profiler.configure`.
    """
    if profiling_enabled != _ENABLED_VALUE:
        logger.debug("PROFILING_ENABLED not set, skipping profiler configuration")
        return None

    if not endpoint:
        logger.debug(
            "OTEL_EXPORTER_OTLP_ENDPOINT not set, skipping profiler configuration"
        )
        return None

    return endpoint


def resolve_source_attributes(
    repository: str, git_ref: str, root_path: str
) -> dict[str, str]:
    """Return the Pyroscope GitHub source-linking resource attributes."""
    if not repository or not git_ref:
        return {}
    attributes = {"service_repository": repository, "service_git_ref": git_ref}
    if root_path:
        attributes["service_root_path"] = root_path
    return attributes


def configure_profiling(service_name: str) -> None:
    """Configure continuous CPU profiling for `service_name`.

    Opt-in: profiling only starts if ``PROFILING_ENABLED`` is set to ``"1"``.
    Reuses ``OTEL_EXPORTER_OTLP_ENDPOINT`` (the same endpoint tracing
    uses) since profiles are posted directly to the OTel Collector, unlike
    the ESP32 firmware pipeline there is no symbolizer hop.

    Call after `configure_tracing()`, which must have already set the global
    TracerProvider for span/profile linking to attach to.
    """
    endpoint = resolve_endpoint(
        os.getenv("PROFILING_ENABLED", ""), os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    )
    if endpoint is None:
        return

    resource_attributes = resolve_source_attributes(
        current_repository(), resolve_current_git_ref(), _ROOT_PATH
    )

    otlp_profiler.configure(
        service_name, endpoint, resource_attributes=resource_attributes
    )
