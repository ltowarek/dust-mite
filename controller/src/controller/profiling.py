"""Dust-mite-specific wiring for the generic `otlp_profiler` package."""

import logging

import otlp_profiler
from controller.otel import resolve_current_git_ref

logger = logging.getLogger(__name__)

_ROOT_PATH = "controller"


def resolve_endpoint(endpoint: str | None, *, enabled: bool) -> str | None:
    """Return the endpoint to profile with, or None if profiling should stay off.

    Pure decision logic factored out of `configure_profiling` so it can be
    tested directly without a test double for `otlp_profiler.configure`.
    """
    if not enabled:
        logger.debug("Profiling not enabled, skipping profiler configuration")
        return None

    if not endpoint:
        logger.debug("No OTLP endpoint, skipping profiler configuration")
        return None

    return endpoint


def resolve_source_attributes(
    repository: str | None, git_ref: str, root_path: str
) -> dict[str, str]:
    """Return the Pyroscope GitHub source-linking resource attributes."""
    if not repository or not git_ref:
        return {}
    attributes = {"service_repository": repository, "service_git_ref": git_ref}
    if root_path:
        attributes["service_root_path"] = root_path
    return attributes


def configure_profiling(
    service_name: str, endpoint: str | None, repository: str | None, *, enabled: bool
) -> None:
    """Configure continuous CPU profiling for `service_name`.

    Opt-in: profiling only starts if ``enabled`` is true. ``endpoint`` is the
    same OTLP base endpoint tracing uses, since profiles are posted directly
    to the OTel Collector; unlike the ESP32 firmware pipeline there is no
    symbolizer hop. Pyroscope links profiles to ``repository``.

    Call after `configure_tracing()`, which must have already set the global
    TracerProvider for span/profile linking to attach to.
    """
    profiling_endpoint = resolve_endpoint(endpoint, enabled=enabled)
    if profiling_endpoint is None:
        return

    resource_attributes = resolve_source_attributes(
        repository, resolve_current_git_ref(), _ROOT_PATH
    )

    otlp_profiler.configure(
        service_name, profiling_endpoint, resource_attributes=resource_attributes
    )
