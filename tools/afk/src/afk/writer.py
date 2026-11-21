"""Carry out a phase's writes with `gh`, or only report them in a dry run."""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum

from afk.effects import Comment, DispatchWorkflow, Effect, ReplaceLabel

Runner = Callable[[Sequence[str], Mapping[str, str]], str]
StepOutput = Callable[[Mapping[str, str]], None]


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
        case ReplaceLabel(number=number, remove=remove, add=add):
            args = [
                "issue",
                "edit",
                str(number),
                "--remove-label",
                remove,
                "--add-label",
                add,
            ]
            return GhCommand(["gh", *args], Token.APP)
        case Comment(number=number, body=body):
            return GhCommand(
                ["gh", "issue", "comment", str(number), "--body", body], Token.APP
            )


class Writer:
    """Route every write of a phase, so that a dry run carries out none."""

    def __init__(self, gh: Runner, env: Mapping[str, str]) -> None:
        """Write through `gh`, with tokens and `AFK_DRY_RUN` from `env`."""
        self._gh = gh
        self._env = env
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

    def outputs(self) -> dict[str, str]:
        """Return the `effects` step output in a dry run, and nothing otherwise."""
        if not self._dry_run:
            return {}
        effects = [{"type": type(e).__name__, **asdict(e)} for e in self._planned]
        return {"effects": json.dumps(effects)}
