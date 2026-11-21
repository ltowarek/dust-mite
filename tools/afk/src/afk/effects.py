"""The writes that a phase plans, one dataclass per kind."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class DispatchWorkflow:
    """Start a workflow on the default branch with string inputs."""

    workflow: str
    inputs: dict[str, str]


@dataclass(frozen=True)
class ReplaceLabel:
    """Replace one label of an issue or pull request with another."""

    number: int
    remove: str
    add: str


@dataclass(frozen=True)
class RemoveLabel:
    """Remove a label from an issue or pull request."""

    number: int
    label: str


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


Effect = DispatchWorkflow | ReplaceLabel | RemoveLabel | Comment | React
