"""The writes that a phase plans, one dataclass per kind."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class DispatchWorkflow:
    """Start a workflow on the default branch with string inputs."""

    workflow: str
    inputs: dict[str, str]


@dataclass(frozen=True)
class EditLabels:
    """Add and remove labels of an issue or pull request in one edit."""

    number: int
    add: tuple[str, ...] = ()
    remove: tuple[str, ...] = ()


@dataclass(frozen=True)
class Comment:
    """Post a conversation comment on an issue or pull request."""

    number: int
    body: str


class Reaction(StrEnum):
    """A reaction to a comment, as GitHub names it."""

    EYES = "eyes"
    CONFUSED = "confused"


@dataclass(frozen=True)
class React:
    """React to a conversation comment."""

    comment_id: int
    content: str


@dataclass(frozen=True)
class PushBranch:
    """Push `HEAD` to a branch of a repository."""

    repository: str
    branch: str


@dataclass(frozen=True)
class CreatePullRequest:
    """Open a draft pull request from a branch into `main`."""

    branch: str
    title: str
    body: str


@dataclass(frozen=True)
class EditPullRequest:
    """Replace the title and body of a branch's open pull request."""

    branch: str
    title: str
    body: str


@dataclass(frozen=True)
class EditPullRequestLabels:
    """Add and remove labels of a branch's open pull request in one edit."""

    branch: str
    add: tuple[str, ...] = ()
    remove: tuple[str, ...] = ()


@dataclass(frozen=True)
class MarkPullRequestReady:
    """Mark a branch's open draft pull request ready for review."""

    branch: str


IssueWrite = EditLabels | Comment | React
"""A write on an issue or its conversation, which `gh issue` or `gh api` makes."""

PullRequestWrite = (
    CreatePullRequest | EditPullRequest | EditPullRequestLabels | MarkPullRequestReady
)
"""A write on a branch's pull request, which `gh pr` makes."""

Effect = DispatchWorkflow | PushBranch | IssueWrite | PullRequestWrite
