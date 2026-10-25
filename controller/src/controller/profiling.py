"""Dust-mite-specific wiring for the generic `otlp_profiler` package."""

import logging

from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv._incubating.attributes.vcs_attributes import (
    VCS_REF_HEAD_REVISION,
    VCS_REPOSITORY_URL_FULL,
)

import otlp_profiler

logger = logging.getLogger(__name__)

_ROOT_PATH = "controller"


def source_link_attributes(resource: Resource) -> dict[str, str]:
    """Return Pyroscope's GitHub source-linking attributes for `resource`.

    Pyroscope reads the repository and revision from its own attribute
    names, not from the OpenTelemetry `vcs.*` ones the resource carries.
    """
    repository = resource.attributes.get(VCS_REPOSITORY_URL_FULL)
    git_ref = resource.attributes.get(VCS_REF_HEAD_REVISION)
    if not isinstance(repository, str) or not isinstance(git_ref, str):
        return {}
    return {
        "service_repository": repository,
        "service_git_ref": git_ref,
        "service_root_path": _ROOT_PATH,
    }


def configure_profiling(endpoint: str | None, resource: Resource) -> None:
    """Export continuous CPU profiles over OTLP/HTTP.

    ``endpoint`` is the full OTLP/HTTP profiles URL, on the OTel Collector:
    unlike the ESP32 firmware pipeline there is no symbolizer hop.
    Configuration is skipped if it is empty.

    Call after `configure_tracing()`, which must have already set the global
    TracerProvider for span/profile linking to attach to.
    """
    if not endpoint:
        logger.debug("No OTLP profiles endpoint, skipping profiler configuration")
        return

    otlp_profiler.configure(
        endpoint, resource.merge(Resource(source_link_attributes(resource)))
    )
