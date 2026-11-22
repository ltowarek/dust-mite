"""End an AFK run: report how it ended, then release or continue its ticket."""

import json
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from afk.effects import (
    CloseIssue,
    Comment,
    CommentPullRequest,
    CreateIssue,
    DispatchWorkflow,
    EditLabels,
    Effect,
    React,
    Reaction,
)
from afk.github import Token, run_gh
from afk.labels import Label
from afk.runner import Runner
from afk.writer import Writer

_STOPPED = {"failure", "cancelled"}
_LINE_BREAK = re.compile(r"\s*\n\s*")
_STEP_SEPARATOR = " \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} "


class Workflow(StrEnum):
    """The AFK run workflows that the finish phase ends."""

    AFK_RUN = "afk-run"
    AFK_RUN_PR = "afk-run-pr"


@dataclass(frozen=True)
class Run:
    """The AFK run that ends."""

    workflow: Workflow
    ticket: int
    comment_id: int | None
    url: str


@dataclass(frozen=True)
class Needs:
    """How the run's check and implement jobs ended, and what they output."""

    check_result: str
    refusal: str
    block: bool
    queue: bool
    spec: bool
    child_ticket: int | None
    branch: str
    last_run: bool
    implement_result: str
    agent_output: Mapping[str, Any]
    agent_error: str
    outcome: str
    needs_car_reason: str
    pr_url: str
    sha: str

    @classmethod
    def parse(cls, needs: Mapping[str, Any]) -> "Needs":
        """Read the finish job's `needs` context."""
        check = needs["check"]["outputs"]
        implement = needs["implement"]["outputs"]
        child_ticket = check.get("child-ticket")
        agent_output = implement.get("agent-output")
        return cls(
            check_result=needs["check"]["result"],
            refusal=check.get("refusal", ""),
            block=check.get("block") == "true",
            queue=check.get("queue") == "true",
            spec=check.get("spec") == "true",
            child_ticket=int(child_ticket) if child_ticket else None,
            branch=check.get("branch", ""),
            last_run=check.get("last-run") == "true",
            implement_result=needs["implement"]["result"],
            agent_output=json.loads(agent_output) if agent_output else {},
            agent_error=implement.get("agent-error", ""),
            outcome=implement.get("outcome", ""),
            needs_car_reason=implement.get("needs-car-reason", ""),
            pr_url=implement.get("pr-url", ""),
            sha=implement.get("sha", ""),
        )

    @property
    def failed(self) -> bool:
        """Whether the check or implement job failed or was cancelled."""
        return self.check_result in _STOPPED or self.implement_result in _STOPPED

    @property
    def implemented(self) -> bool:
        """Whether the implement job succeeded."""
        return self.implement_result == "success"


def failed_step(response: Mapping[str, Any]) -> str | None:
    """Return the first failed or cancelled job of a run attempt, with its step."""
    for job in response["jobs"]:
        steps = job.get("steps") or []
        stopped = [s["name"] for s in steps if s["conclusion"] in _STOPPED]
        if job["conclusion"] in _STOPPED or any(
            s["conclusion"] == "failure" for s in steps
        ):
            return _STEP_SEPARATOR.join([job["name"], *stopped[:1]])
    return None


def _worked(run: Run, needs: Needs) -> int:
    return needs.child_ticket or run.ticket


def _stopped(run: Run, text: str, reason: str, then: str) -> list[Effect]:
    body = f"{text}.\n\n**Reason:** {reason}\n\n**Run:** {run.url}\n\n{then}\n"
    return [
        EditLabels(number=run.ticket, add=(Label.BLOCKED,)),
        Comment(number=run.ticket, body=body),
    ]


def _refuse(run: Run, needs: Needs) -> list[Effect]:
    if not needs.refusal:
        return []
    label: list[Effect] = [EditLabels(number=run.ticket, add=(Label.BLOCKED,))]
    return [
        *(label if needs.block else []),
        Comment(number=run.ticket, body=needs.refusal),
    ]


def _follow_ups(run: Run, needs: Needs) -> list[Effect]:
    header = (
        "> *Follow-up ticket filed by an AFK agent session while working "
        f"#{_worked(run, needs)}.* ([run]({run.url}))"
    )
    return [
        CreateIssue(
            title=follow_up["title"],
            body=f"{header}\n\n{follow_up['body']}\n",
            labels=(
                "needs-triage",
                "source:follow-up",
                follow_up["type"],
                *follow_up["components"],
            ),
        )
        for follow_up in needs.agent_output.get("follow_ups", [])
    ]


def _already_covered(run: Run, needs: Needs) -> list[Effect]:
    lines = [
        f"- {_LINE_BREAK.sub(' ', item['problem'])} Covered by #{item['covered_by']}."
        for item in needs.agent_output.get("already_covered", [])
    ]
    if not lines:
        return []
    body = "## Follow-ups already covered\n\n{}\n".format("\n".join(lines))
    if run.workflow == Workflow.AFK_RUN_PR:
        return [Comment(number=run.ticket, body=body)]
    if not needs.pr_url:
        return []
    return [CommentPullRequest(branch=needs.branch, body=body)]


def _close_child_ticket(run: Run, needs: Needs) -> list[Effect]:
    if not (needs.spec and needs.sha):
        return []
    return [
        CloseIssue(number=_worked(run, needs), comment=f"Implemented in {needs.sha}")
    ]


def _clear_blocked(run: Run, needs: Needs) -> list[Effect]:
    if not needs.implemented:
        return []
    return [EditLabels(number=run.ticket, remove=(Label.BLOCKED,))]


def _stop_spec(run: Run, needs: Needs) -> list[Effect]:
    if not (needs.spec and needs.implemented and not needs.sha):
        return []
    if needs.outcome == "needs_car":
        reason = f"Finding the fix needs the car: {needs.needs_car_reason}"
    else:
        reason = "It has a spec gap, whose questions are on it."
    return _stopped(
        run,
        f"AFK spec implementation stopped at child ticket #{_worked(run, needs)}",
        reason,
        "Comment `/afk implement` to resume it.",
    )


def _report_failure(run: Run, needs: Needs, step: str) -> list[Effect]:
    reason = f"`{step}` failed."
    if needs.agent_error:
        reason = f"{reason} The agent reported: {needs.agent_error}"
    text = "The AFK run failed"
    if run.workflow == Workflow.AFK_RUN_PR:
        text = "The AFK run on this PR failed"
    elif needs.spec:
        text = f"The AFK run failed on child ticket #{_worked(run, needs)}"
    return _stopped(run, text, reason, "Comment `/afk implement` to retry.")


def _queue(run: Run) -> list[Effect]:
    # The marker carries the AFK command to the run that promote-queued dispatches.
    marker = f"<!-- afk-command: {run.comment_id or ''} -->"
    return [
        EditLabels(number=run.ticket, add=(Label.QUEUED,)),
        Comment(
            number=run.ticket,
            body=f"Queued (`{Label.QUEUED}`) until one of its child tickets is "
            f"unblocked. {marker}",
        ),
    ]


def _dispatch_next_run(run: Run) -> list[Effect]:
    inputs = {"number": str(run.ticket)}
    if run.comment_id is not None:
        inputs["comment-id"] = str(run.comment_id)
    return [DispatchWorkflow(workflow="afk-run.yml", inputs=inputs)]


def _release(run: Run) -> list[Effect]:
    return [EditLabels(number=run.ticket, remove=(Label.IN_PROGRESS,))]


def _react(run: Run, content: Reaction) -> list[Effect]:
    if run.comment_id is None:
        return []
    return [React(comment_id=run.comment_id, content=content)]


def plan(run: Run, needs: Needs, step: str | None) -> list[Effect]:
    """Return the run's last writes, given the failed step when a job failed."""
    effects = [
        *_refuse(run, needs),
        *_follow_ups(run, needs),
        *_already_covered(run, needs),
        *_close_child_ticket(run, needs),
        *_clear_blocked(run, needs),
        *_stop_spec(run, needs),
    ]
    if needs.failed:
        effects += _report_failure(run, needs, step or "unknown step")
    # A queued or continued spec keeps the command's reaction until it ends.
    if needs.queue:
        return [*effects, *_queue(run), *_release(run)]
    if needs.spec and needs.sha and not needs.last_run:
        return [*effects, *_dispatch_next_run(run)]
    # A PR run has no outcome: its work is done when its implement job succeeds.
    outcome = "done" if run.workflow == Workflow.AFK_RUN_PR else needs.outcome
    done = not needs.refusal and needs.implemented and outcome == "done"
    reaction = Reaction.ROCKET if done else Reaction.CONFUSED
    return [*effects, *_release(run), *_react(run, reaction)]


def plan_failure(run: Run, needs: Needs, failed: str) -> list[Effect]:
    """Return the writes that report and release the ticket after `failed` failed."""
    return [
        *_report_failure(run, needs, f"finish{_STEP_SEPARATOR}{failed}"),
        *_release(run),
        *_react(run, Reaction.CONFUSED),
    ]


def _finished(env: Mapping[str, str]) -> Run:
    repository = env["GH_REPO"]
    comment_id = env.get("AFK_COMMENT_ID", "")
    return Run(
        workflow=Workflow(env["AFK_WORKFLOW"]),
        ticket=int(env["AFK_TICKET"]),
        comment_id=int(comment_id) if comment_id else None,
        url=f"{env['GITHUB_SERVER_URL']}/{repository}/actions/runs/"
        f"{env['GITHUB_RUN_ID']}",
    )


def _read_failed_step(gh: Runner, env: Mapping[str, str]) -> str | None:
    endpoint = (
        f"repos/{env['GH_REPO']}/actions/runs/{env['GITHUB_RUN_ID']}"
        f"/attempts/{env['GITHUB_RUN_ATTEMPT']}/jobs?per_page=100"
    )
    return failed_step(json.loads(run_gh(gh, env, Token.WORKFLOW, ["api", endpoint])))


def run(gh: Runner, env: Mapping[str, str], writer: Writer) -> None:
    """Make the run's last writes; after a failed one, report and release the ticket."""
    finished = _finished(env)
    needs = Needs.parse(json.loads(env["AFK_NEEDS"]))
    doing = "Read the failed step"
    try:
        step = _read_failed_step(gh, env) if needs.failed else None
        for effect in plan(finished, needs, step):
            doing = type(effect).__name__
            writer.write(effect)
    except subprocess.CalledProcessError:
        for effect in plan_failure(finished, needs, doing):
            writer.write(effect)
        raise
