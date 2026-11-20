"""Carry out a phase's writes with `gh`, or only report them in a dry run."""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict

from afk.effects import Comment, DispatchWorkflow, Effect, ReplaceLabel

Runner = Callable[[Sequence[str], Mapping[str, str]], str]

AS_APP = "AFK_APP_TOKEN"
AS_WORKFLOW = "AFK_WORKFLOW_TOKEN"


def command(effect: Effect) -> tuple[list[str], str]:
    """Return the `gh` arguments for a write and the variable that holds its token."""
    match effect:
        case DispatchWorkflow(workflow=workflow, inputs=inputs):
            fields = [
                arg for key, value in inputs.items() for arg in ("-f", f"{key}={value}")
            ]
            # The App has no Actions write permission, so it cannot dispatch.
            return ["gh", "workflow", "run", workflow, *fields], AS_WORKFLOW
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
            return ["gh", *args], AS_APP
        case Comment(number=number, body=body):
            return ["gh", "issue", "comment", str(number), "--body", body], AS_APP


class Writer:
    """Route every write of a phase, so that a dry run carries out none."""

    def __init__(self, run: Runner, env: Mapping[str, str]) -> None:
        """Write through `run`, with tokens and `AFK_DRY_RUN` from `env`."""
        self._run = run
        self._env = env
        self._dry_run = env.get("AFK_DRY_RUN") == "true"
        self._planned: list[Effect] = []

    def __call__(self, effect: Effect) -> None:
        """Carry out `effect`, or only record it in a dry run."""
        self._planned.append(effect)
        if self._dry_run:
            return
        args, token = command(effect)
        self._run(args, {**self._env, "GH_TOKEN": self._env[token]})

    def outputs(self) -> dict[str, str]:
        """Return the `effects` step output in a dry run, and nothing otherwise."""
        if not self._dry_run:
            return {}
        effects = [{"type": type(e).__name__, **asdict(e)} for e in self._planned]
        return {"effects": json.dumps(effects)}
