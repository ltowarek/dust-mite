"""Publish an AFK run's work from the agent's structured output."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from afk.agent import already_covered, read_agent_error, refuse_protected_changes
from afk.effects import (
    Comment,
    CreatePullRequest,
    EditLabels,
    EditPullRequest,
    EditPullRequestLabels,
    Effect,
    MarkPullRequestReady,
    PushBranch,
)
from afk.git import read_head
from afk.github import Token, run_gh
from afk.labels import needs_car
from afk.runner import Runner
from afk.writer import Writer


@dataclass(frozen=True)
class Run:
    """The AFK run whose work is published."""

    repository: str
    ticket: int
    worked_ticket: int
    branch: str
    last_run: bool
    url: str


def _done(output: Mapping[str, Any], run: Run, open_pr: str | None) -> list[Effect]:
    pr_body = output.get("pr_body", "")
    body = f"Closes #{run.ticket}\n\n{pr_body}\n\n[AFK run]({run.url})\n"
    title = output.get("pr_title", "")
    effects: list[Effect] = [PushBranch(repository=run.repository, branch=run.branch)]
    if open_pr is None:
        effects.append(CreatePullRequest(branch=run.branch, title=title, body=body))
    elif run.last_run:
        effects.append(EditPullRequest(branch=run.branch, title=title, body=body))
    # Only the last run hands the PR on, so an incomplete spec stays a draft.
    if not run.last_run:
        return effects
    if output["needs_dut_run"]:
        label = needs_car(output.get("car_variant", ""))
        effects.append(EditPullRequestLabels(branch=run.branch, add=(label,)))
    else:
        effects.append(MarkPullRequestReady(branch=run.branch))
    return effects


def _needs_car(output: Mapping[str, Any], run: Run) -> list[Effect]:
    body = (
        "Finding the fix needs the car, so this AFK run pushed nothing.\n\n"
        f"**Reason:** {output.get('needs_car_reason', '')}\n\n**Run:** {run.url}\n"
        f"{already_covered(output)}"
    )
    return [
        EditLabels(
            number=run.worked_ticket,
            add=(needs_car(output.get("car_variant", "")),),
        ),
        Comment(number=run.worked_ticket, body=body),
    ]


def _spec_gap(output: Mapping[str, Any], run: Run) -> list[Effect]:
    body = (
        "> *Spec gap found by an AFK agent session while working this ticket.* "
        f"([run]({run.url}))\n\n{output.get('spec_gaps', '')}\n"
        f"{already_covered(output)}"
    )
    return [
        EditLabels(
            number=run.worked_ticket,
            add=("needs-triage",),
            remove=("ready-for-agent",),
        ),
        Comment(number=run.worked_ticket, body=body),
    ]


def plan(output: Mapping[str, Any], run: Run, open_pr: str | None) -> list[Effect]:
    """Return the writes that publish the agent's work, or hand its ticket on."""
    match output["outcome"]:
        case "needs_car":
            return _needs_car(output, run)
        case "spec_gap":
            return _spec_gap(output, run)
        case "done":
            return _done(output, run, open_pr)
        case outcome:
            msg = f"Unknown outcome: {outcome}"
            raise ValueError(msg)


def open_pull_request(response: list[dict[str, Any]]) -> str | None:
    """Return the URL of the branch's open PR from `gh pr list`."""
    return str(response[0]["url"]) if response else None


def _read_open_pull_request(
    gh: Runner, env: Mapping[str, str], branch: str
) -> str | None:
    args = ["pr", "list", "--head", branch, "--state", "open", "--json", "url"]
    return open_pull_request(json.loads(run_gh(gh, env, Token.APP, args)))


def _published(env: Mapping[str, str]) -> Run:
    repository = env["GH_REPO"]
    return Run(
        repository=repository,
        ticket=int(env["AFK_TICKET"]),
        worked_ticket=int(env["AFK_WORKED_TICKET"]),
        branch=env["AFK_BRANCH"],
        last_run=env["AFK_LAST_RUN"] == "true",
        url=f"{env['GITHUB_SERVER_URL']}/{repository}/actions/runs/"
        f"{env['GITHUB_RUN_ID']}",
    )


def run(gh: Runner, git: Runner, env: Mapping[str, str], writer: Writer) -> None:
    """Refuse protected changes, then publish the work or hand the ticket on."""
    if env["AFK_AGENT_OUTCOME"] != "success":
        writer.set_output("agent-error", read_agent_error(env))
        return
    refuse_protected_changes(git, env, env["AFK_BASE"])
    output = json.loads(env["AFK_AGENT_OUTPUT"])
    published = _published(env)
    done = output["outcome"] == "done"
    open_pr = _read_open_pull_request(gh, env, published.branch) if done else None
    writer.set_output("outcome", output["outcome"])
    writer.set_output("needs-car-reason", output.get("needs_car_reason", ""))
    for effect in plan(output, published, open_pr):
        writer.write(effect)
    if done:
        pr_url = _read_open_pull_request(gh, env, published.branch)
        writer.set_output("pr-url", pr_url or "")
        writer.set_output("sha", read_head(git, env))
