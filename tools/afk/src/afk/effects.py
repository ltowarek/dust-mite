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
    ROCKET = "rocket"


@dataclass(frozen=True)
class React:
    """React to a conversation comment."""

    comment_id: int
    content: str


@dataclass(frozen=True)
class PushBranch:
    """Push `HEAD` to a branch of a repository, only from `lease` when set."""

    repository: str
    branch: str
    lease: str | None = None


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


@dataclass(frozen=True)
class CommentPullRequest:
    """Post a conversation comment on a branch's open pull request."""

    branch: str
    body: str


@dataclass(frozen=True)
class ReplyToReviewComment:
    """Reply in the review thread that a PR's review comment starts."""

    number: int
    comment_id: int
    body: str


@dataclass(frozen=True)
class CreateReviewComment:
    """Comment on a line of a PR's diff at a commit."""

    number: int
    commit: str
    path: str
    line: int
    body: str


@dataclass(frozen=True)
class CreateIssue:
    """Open an issue with labels."""

    title: str
    body: str
    labels: tuple[str, ...]


@dataclass(frozen=True)
class CloseIssue:
    """Close an issue with a comment."""

    number: int
    comment: str


IssueWrite = EditLabels | Comment | React | CreateIssue | CloseIssue
"""A write on an issue or its conversation, which `gh issue` or `gh api` makes."""

PullRequestWrite = (
    CreatePullRequest
    | EditPullRequest
    | EditPullRequestLabels
    | MarkPullRequestReady
    | CommentPullRequest
)
"""A write on a branch's pull request, which `gh pr` makes."""

ReviewWrite = ReplyToReviewComment | CreateReviewComment
"""A review comment on a pull request, which `gh api` makes."""

Effect = DispatchWorkflow | PushBranch | IssueWrite | PullRequestWrite | ReviewWrite
