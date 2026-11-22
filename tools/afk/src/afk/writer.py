"""Carry out a phase's writes with `gh`, or report them in a dry run; set outputs."""

import json
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import TextIO

from afk.effects import (
    AddPullRequestLabel,
    Comment,
    CreatePullRequest,
    DispatchWorkflow,
    EditLabels,
    EditPullRequest,
    Effect,
    MarkPullRequestReady,
    PushBranch,
    React,
)

Runner = Callable[[Sequence[str], Mapping[str, str]], str]


class Token(StrEnum):
    """The environment variable that holds a command's token."""

    APP = "AFK_APP_TOKEN"
    WORKFLOW = "AFK_WORKFLOW_TOKEN"


def run_gh(
    gh: Runner, env: Mapping[str, str], token: Token, args: Sequence[str]
) -> str:
    """Run a gh command with `token` as its GH_TOKEN."""
    return gh(args, {**env, "GH_TOKEN": env[token]})


@dataclass(frozen=True)
class GhCommand:
    """A `gh` command line and the variable that holds the token it runs with."""

    args: list[str]
    token: Token


def gh_command(effect: Effect) -> GhCommand:
    """Return the command that carries out a write."""
    match effect:
        case DispatchWorkflow(workflow=workflow, inputs=inputs):
            fields = [
                arg for key, value in inputs.items() for arg in ("-f", f"{key}={value}")
            ]
            # The App has no Actions write permission, so it cannot dispatch.
            return GhCommand(
                ["gh", "workflow", "run", workflow, *fields], Token.WORKFLOW
            )
        case EditLabels(number=number, add=add, remove=remove):
            flags = [
                *(arg for label in add for arg in ("--add-label", label)),
                *(arg for label in remove for arg in ("--remove-label", label)),
            ]
            args = ["gh", "issue", "edit", str(number), *flags]
        case Comment(number=number, body=body):
            args = ["gh", "issue", "comment", str(number), "--body", body]
        case React(comment_id=comment_id, content=content):
            # gh has no reaction subcommand; gh api takes {owner}/{repo} from GH_REPO.
            endpoint = (
                f"repos/{{owner}}/{{repo}}/issues/comments/{comment_id}/reactions"
            )
            args = ["gh", "api", "--method", "POST", endpoint]
            args += ["-f", f"content={content}"]
        case PushBranch(repository=repository, branch=branch):
            args = _push(repository, branch)
        case CreatePullRequest(branch=branch, title=title, body=body):
            pr = ["--base", "main", "--head", branch, "--title", title, "--body", body]
            args = ["gh", "pr", "create", "--draft", *pr]
        case EditPullRequest(branch=branch, title=title, body=body):
            args = ["gh", "pr", "edit", branch, "--title", title, "--body", body]
        case AddPullRequestLabel(branch=branch, label=label):
            args = ["gh", "pr", "edit", branch, "--add-label", label]
        case MarkPullRequestReady(branch=branch):
            args = ["gh", "pr", "ready", branch]
    return GhCommand(args, Token.APP)


def _push(repository: str, branch: str) -> list[str]:
    # Keeps the token from the arguments and the agent's hooks and credential helpers.
    return [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "credential.helper=",
        "-c",
        "credential.helper=!gh auth git-credential",
        "push",
        f"https://github.com/{repository}.git",
        f"HEAD:refs/heads/{branch}",
    ]


def write_outputs(output: TextIO, outputs: Mapping[str, str]) -> None:
    """Write step outputs in the multiline form, so no value can add an output."""
    delimiter = f"afk_{secrets.token_hex(16)}"
    output.writelines(
        f"{name}<<{delimiter}\n{value}\n{delimiter}\n"
        for name, value in outputs.items()
    )


class Writer:
    """Route every write of a phase, so that a dry run carries out none."""

    def __init__(self, gh: Runner, env: Mapping[str, str], output: Path) -> None:
        """Write through `gh`, with tokens and `AFK_DRY_RUN` from `env`, to `output`."""
        self._gh = gh
        self._env = env
        self._output = output
        self._dry_run = env.get("AFK_DRY_RUN") == "true"
        self._planned: list[Effect] = []

    def write(self, effect: Effect) -> None:
        """Carry out `effect`, or only record it in a dry run."""
        self._planned.append(effect)
        if self._dry_run:
            return
        invocation = gh_command(effect)
        run_gh(self._gh, self._env, invocation.token, invocation.args)

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
