"""The pull request that an AFK run on a PR works on."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PullRequest:
    """A pull request's number and branch, and the head that a run on it starts from."""

    number: int
    branch: str
    head_sha: str
