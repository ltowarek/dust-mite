"""Dust-mite-specific OpenTelemetry helpers shared across signals."""

import re
from importlib.metadata import PackageNotFoundError, version

from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.semconv._incubating.attributes.vcs_attributes import (
    VCS_REF_HEAD_REVISION,
    VCS_REPOSITORY_URL_FULL,
)

_COMMIT_ID_RE = re.compile(r"\+g([0-9a-f]+)")


def resolve_git_ref(package_version: str) -> str:
    """Extract the short commit hash from a `setuptools_scm`-derived version."""
    match = _COMMIT_ID_RE.search(package_version)
    return match.group(1) if match else ""


def resolve_current_git_ref() -> str:
    """Return the running process's own git ref, or "" if unavailable."""
    try:
        return resolve_git_ref(version("controller"))
    except PackageNotFoundError:
        return ""


def resolve_vcs_attributes(repository: str | None, git_ref: str) -> dict[str, str]:
    """Return OpenTelemetry `vcs.*` resource attributes, or {} if unset."""
    if not repository or not git_ref:
        return {}
    return {
        VCS_REPOSITORY_URL_FULL: repository,
        VCS_REF_HEAD_REVISION: git_ref,
    }


def service_resource(service_name: str, repository: str | None) -> Resource:
    """Return the resource every signal of `service_name` is exported with."""
    vcs_attributes = resolve_vcs_attributes(repository, resolve_current_git_ref())
    return Resource.create({SERVICE_NAME: service_name, **vcs_attributes})
