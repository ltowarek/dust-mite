"""The writes that a phase plans, one dataclass per kind."""

from dataclasses import dataclass


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
class Comment:
    """Post a conversation comment on an issue or pull request."""

    number: int
    body: str


Effect = DispatchWorkflow | ReplaceLabel | Comment
