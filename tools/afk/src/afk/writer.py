"""Carry out a phase's writes with `gh` or `git`, or report them in a dry run."""

import json
import secrets
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TextIO, assert_never

from afk.effects import (
    CloseIssue,
    Comment,
    CommentPullRequest,
    CreateIssue,
    CreatePullRequest,
    CreateReviewComment,
    DispatchWorkflow,
    EditLabels,
    EditPullRequest,
    EditPullRequestLabels,
    Effect,
    MarkPullRequestReady,
    PushBranch,
    React,
    ReplyToReviewComment,
    Unreact,
)
from afk.git import push_args, run_git
from afk.github import (
    Token,
    dispatch_args,
    issue_args,
    pull_request_args,
    review_args,
    run_gh,
)
from afk.runner import Runner


@dataclass(frozen=True)
class GhCommand:
    """A `gh` call's arguments, and the variable that holds its token."""

    args: list[str]
    token: Token


@dataclass(frozen=True)
class GitCommand:
    """A `git` call's arguments, and the variable that holds its token, if any."""

    args: list[str]
    token: Token | None


Command = GhCommand | GitCommand


def command_for(effect: Effect) -> Command:
    """Return the command that carries out a write."""
    command: Command
    match effect:
        case DispatchWorkflow(workflow=workflow, inputs=inputs):
            # The App has no Actions write permission, so it cannot dispatch.
            command = GhCommand(dispatch_args(workflow, inputs), Token.WORKFLOW)
        case PushBranch(repository=repository, branch=branch, lease=lease):
            command = GitCommand(push_args(repository, branch, lease), Token.APP)
        case (
            EditLabels()
            | Comment()
            | React()
            | Unreact()
            | CreateIssue()
            | CloseIssue()
        ):
            command = GhCommand(issue_args(effect), Token.APP)
        case (
            CreatePullRequest()
            | EditPullRequest()
            | EditPullRequestLabels()
            | MarkPullRequestReady()
            | CommentPullRequest()
        ):
            command = GhCommand(pull_request_args(effect), Token.APP)
        case ReplyToReviewComment() | CreateReviewComment():
            command = GhCommand(review_args(effect), Token.APP)
        case _:
            assert_never(effect)
    return command


def write_outputs(output: TextIO, outputs: Mapping[str, str]) -> None:
    """Write step outputs in the multiline form, so no value can add an output."""
    delimiter = f"afk_{secrets.token_hex(16)}"
    output.writelines(
        f"{name}<<{delimiter}\n{value}\n{delimiter}\n"
        for name, value in outputs.items()
    )


class Writer:
    """Route every write of a phase, so that a dry run carries out none."""

    def __init__(
        self, gh: Runner, git: Runner, env: Mapping[str, str], output: Path
    ) -> None:
        """Write through `gh` and `git`, with tokens and `AFK_DRY_RUN` from `env`."""
        self._gh = gh
        self._git = git
        self._env = env
        self._output = output
        self._dry_run = env.get("AFK_DRY_RUN") == "true"
        self._planned: list[Effect] = []

    def write(self, effect: Effect) -> None:
        """Carry out `effect`, or only record it in a dry run."""
        self._planned.append(effect)
        if self._dry_run:
            return
        match command_for(effect):
            case GhCommand(args=args, token=token):
                run_gh(self._gh, self._env, token, args)
            case GitCommand(args=args, token=token):
                secret = None if token is None else self._env[token]
                run_git(self._git, self._env, args, secret)
            case command:
                assert_never(command)

    def set_output(self, name: str, value: str) -> None:
        """Set a step output now, so that it outlives a later write that fails."""
        # Append: earlier writes in the same step stay outputs.
        with self._output.open("a") as output:
            write_outputs(output, {name: value})

    def report(self) -> None:
        """Set the `effects` step output in a dry run, and nothing otherwise."""
        if self._dry_run:
            effects = [{"type": type(e).__name__, **asdict(e)} for e in self._planned]
            self.set_output("effects", json.dumps(effects))
