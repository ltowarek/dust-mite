"""Decide whether an AFK update-branch run refuses or proceeds."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from afk.effects import EditLabels
from afk.github import PullRequest, Token, run_gh
from afk.labels import Label
from afk.runner import Runner
from afk.writer import Writer


@dataclass(frozen=True)
class State:
    """What the shell read about the pull request, with its state as `gh` names it."""

    pull_request: PullRequest
    url: str
    state: str
    fork: bool


def pull_request_state(view: Mapping[str, Any]) -> State:
    """Return the pull request's state from `gh pr view`."""
    return State(
        pull_request=PullRequest(
            number=view["number"],
            branch=view["headRefName"],
            head_sha=view["headRefOid"],
        ),
        url=view["url"],
        state=view["state"],
        fork=view["isCrossRepository"],
    )


@dataclass(frozen=True)
class CheckResult:
    """Whether an AFK update-branch run is refused, or what it works on."""

    refusal: str | None = None
    url: str | None = None
    pull_request: PullRequest | None = None


def outputs(result: CheckResult) -> dict[str, str]:
    """Return the check job's step outputs; an unset field sets none."""
    pr = result.pull_request
    values = {
        "refusal": result.refusal,
        "url": result.url,
        "branch": None if pr is None else pr.branch,
        "head-sha": None if pr is None else pr.head_sha,
    }
    return {name: value for name, value in values.items() if value is not None}


def check(state: State | None, head_sha: str) -> CheckResult:
    """Decide whether the run goes ahead on the PR, whose state is None for an issue."""
    if state is None:
        return CheckResult(
            refusal="Refused to run: this is not a PR, and `/afk update-branch` "
            "works only on a PR."
        )
    if state.state != "OPEN":
        return CheckResult(refusal=f"Refused to run: this PR is {state.state.lower()}.")
    if state.fork:
        return CheckResult(
            refusal="Refused to run: this PR's branch is in a fork, and an AFK run "
            "never runs a fork's code with the repository's secrets."
        )
    return CheckResult(
        url=state.url,
        pull_request=replace(
            state.pull_request, head_sha=head_sha or state.pull_request.head_sha
        ),
    )


def _read_state(gh: Runner, env: Mapping[str, str], number: str) -> State | None:
    # `gh pr view` fails on an issue, so the issues API tells the two apart.
    issue = json.loads(
        run_gh(
            gh, env, Token.WORKFLOW, ["api", f"repos/{env['GH_REPO']}/issues/{number}"]
        )
    )
    if issue.get("pull_request") is None:
        return None
    view_fields = "number,state,url,isCrossRepository,headRefName,headRefOid"
    view = json.loads(
        run_gh(gh, env, Token.WORKFLOW, ["pr", "view", number, "--json", view_fields])
    )
    return pull_request_state(view)


def run(gh: Runner, env: Mapping[str, str], writer: Writer) -> None:
    """Mark the target in progress, then decide whether its run goes ahead."""
    number = env["AFK_PR"]
    # A run started from the Actions tab has no dispatcher to add the label.
    writer.write(EditLabels(number=int(number), add=(Label.IN_PROGRESS,)))
    result = check(_read_state(gh, env, number), env.get("AFK_HEAD_SHA", ""))
    for name, value in outputs(result).items():
        writer.set_output(name, value)
