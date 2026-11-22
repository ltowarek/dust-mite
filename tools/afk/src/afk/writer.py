"""Carry out a phase's writes with `gh`, or report them in a dry run; set outputs."""

import json
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import TextIO

from afk.effects import (
    Comment,
    DispatchWorkflow,
    EditLabels,
    Effect,
    React,
)

Runner = Callable[[Sequence[str], Mapping[str, str]], str]


class Token(StrEnum):
    """The environment variable that holds a command's token."""

    APP = "AFK_APP_TOKEN"
    WORKFLOW = "AFK_WORKFLOW_TOKEN"


@dataclass(frozen=True)
class GhCommand:
    """A `gh` command line and the variable that holds the token it runs with."""

    args: list[str]
    token: Token


def gh_command(effect: Effect) -> GhCommand:
    """Return the `gh` command that carries out a write."""
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
            return GhCommand(["gh", "issue", "edit", str(number), *flags], Token.APP)
        case Comment(number=number, body=body):
            return GhCommand(
                ["gh", "issue", "comment", str(number), "--body", body], Token.APP
            )
        case React(comment_id=comment_id, content=content):
            # gh has no reaction subcommand; gh api takes {owner}/{repo} from GH_REPO.
            endpoint = (
                f"repos/{{owner}}/{{repo}}/issues/comments/{comment_id}/reactions"
            )
            args = ["api", "--method", "POST", endpoint, "-f", f"content={content}"]
            return GhCommand(["gh", *args], Token.APP)


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
        self._gh(
            invocation.args, {**self._env, "GH_TOKEN": self._env[invocation.token]}
        )

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
