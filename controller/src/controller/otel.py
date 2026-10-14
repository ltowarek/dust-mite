"""Dust-mite-specific OpenTelemetry helpers shared across signals."""

import re
from importlib.metadata import PackageNotFoundError, version

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


def resolve_vcs_attributes(repository: str, git_ref: str) -> dict[str, str]:
    """Return OpenTelemetry `vcs.*` resource attributes, or {} if unset."""
    if not repository or not git_ref:
        return {}
    return {
        "vcs.repository.url.full": repository,
        "vcs.ref.head.revision": git_ref,
    }
