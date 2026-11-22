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


Effect = DispatchWorkflow | EditLabels | Comment | React
