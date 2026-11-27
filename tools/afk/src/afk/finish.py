"""End an AFK run: report how it ended, then release or continue its ticket."""

import json
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from afk.agent import already_covered
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
    Unreact,
)
from afk.github import Token, read_own_reaction, run_gh
from afk.labels import Label
from afk.runner import Runner
from afk.writer import Writer

_STOPPED = {"failure", "cancelled"}
_STEP_SEPARATOR = " \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} "
# The runner adds it to every failed step, so it names no cause.
_EXIT_CODE = re.compile(r"Process completed with exit code \d+\.")


class Workflow(StrEnum):
    """The AFK run workflows that the finish phase ends."""

    AFK_RUN = "afk-run"
    AFK_RUN_PR = "afk-run-pr"
    AFK_UPDATE_BRANCH = "afk-update-branch"

    @property
    def work_job(self) -> str:
        """The id of the job that does the run's work."""
        return "update-branch" if self == Workflow.AFK_UPDATE_BRANCH else "implement"

    @property
    def command(self) -> str:
        """The AFK command that retries the run."""
        if self == Workflow.AFK_UPDATE_BRANCH:
            return "/afk update-branch"
        return "/afk implement"


@dataclass(frozen=True)
class Run:
    """The AFK run that ends."""

    workflow: Workflow
    number: int
    comment_id: int | None
    url: str
    # The App's 👀 on the AFK command, which the end reaction replaces.
    eyes: int | None = None

    @property
    def on_pr(self) -> bool:
        """Whether the run worked on a PR rather than a ticket."""
        return self.workflow != Workflow.AFK_RUN


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
    work_result: str
    agent_output: Mapping[str, Any]
    agent_error: str
    outcome: str
    needs_car_reason: str
    pr_url: str
    sha: str

    @classmethod
    def parse(cls, needs: Mapping[str, Any], workflow: Workflow) -> "Needs":
        """Read the finish job's `needs` context, with `workflow`'s work job."""
        check = needs["check"]["outputs"]
        implement = needs[workflow.work_job]["outputs"]
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
            work_result=needs[workflow.work_job]["result"],
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
        return self.check_result in _STOPPED or self.work_result in _STOPPED

    @property
    def implemented(self) -> bool:
        """Whether the implement job succeeded."""
        return self.work_result == "success"


@dataclass(frozen=True)
class FailedStep:
    """A run's failed step, named after its job, and the errors its job reported."""

    name: str
    job_id: int | None = None
    errors: tuple[str, ...] = ()


def failed_step(response: Mapping[str, Any]) -> FailedStep | None:
    """Return the first failed or cancelled job of a run attempt, with its step."""
    for job in response["jobs"]:
        steps = job.get("steps") or []
        stopped = [s["name"] for s in steps if s["conclusion"] in _STOPPED]
        if job["conclusion"] in _STOPPED or any(
            s["conclusion"] == "failure" for s in steps
        ):
            name = _STEP_SEPARATOR.join([job["name"], *stopped[:1]])
            return FailedStep(name=name, job_id=job["id"])
    return None


def job_errors(annotations: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Return the messages of a job's failure annotations that name a cause."""
    return tuple(
        a["message"]
        for a in annotations
        if a["annotation_level"] == "failure" and not _EXIT_CODE.fullmatch(a["message"])
    )


def _worked(run: Run, needs: Needs) -> int:
    return needs.child_ticket or run.number


def _stopped(run: Run, text: str, reason: str, then: str) -> list[Effect]:
    body = f"{text}.\n\n**Reason:** {reason}\n\n**Run:** {run.url}\n\n{then}\n"
    return [
        EditLabels(number=run.number, add=(Label.BLOCKED,)),
        Comment(number=run.number, body=body),
    ]


def _refuse(run: Run, needs: Needs) -> list[Effect]:
    if not needs.refusal:
        return []
    label: list[Effect] = [EditLabels(number=run.number, add=(Label.BLOCKED,))]
    return [
        *(label if needs.block else []),
        Comment(number=run.number, body=needs.refusal),
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
    # A branch update lists them in its merge comment.
    if run.workflow == Workflow.AFK_UPDATE_BRANCH:
        return []
    body = already_covered(needs.agent_output).lstrip()
    if not body:
        return []
    if run.on_pr:
        return [Comment(number=run.number, body=body)]
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
    return [EditLabels(number=run.number, remove=(Label.BLOCKED,))]


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


def _quote(text: str) -> str:
    return "\n".join(f"> {line}".rstrip() for line in text.splitlines())


def _report_failure(run: Run, needs: Needs, step: FailedStep) -> list[Effect]:
    reason = f"`{step.name}` failed."
    if needs.agent_error:
        reason = f"{reason} The agent reported: {needs.agent_error}"
    errors = [error for error in step.errors if error != needs.agent_error]
    if errors:
        reason = f"{reason} Its job reported:\n\n" + "\n\n".join(map(_quote, errors))
    text = "The AFK run failed"
    if run.workflow == Workflow.AFK_UPDATE_BRANCH:
        text = "The AFK run that updates this PR's branch failed"
    elif run.on_pr:
        text = "The AFK run on this PR failed"
    elif needs.spec:
        text = f"The AFK run failed on child ticket #{_worked(run, needs)}"
    return _stopped(run, text, reason, f"Comment `{run.workflow.command}` to retry.")


def _queue(run: Run) -> list[Effect]:
    # The marker carries the AFK command to the run that promote-queued dispatches.
    marker = f"<!-- afk-command: {run.comment_id or ''} -->"
    return [
        EditLabels(number=run.number, add=(Label.QUEUED,)),
        Comment(
            number=run.number,
            body=f"Queued (`{Label.QUEUED}`) until one of its child tickets is "
            f"unblocked. {marker}",
        ),
    ]


def _dispatch_next_run(run: Run) -> list[Effect]:
    inputs = {"number": str(run.number)}
    if run.comment_id is not None:
        inputs["comment-id"] = str(run.comment_id)
    return [DispatchWorkflow(workflow="afk-run.yml", inputs=inputs)]


def _release(run: Run) -> list[Effect]:
    return [EditLabels(number=run.number, remove=(Label.IN_PROGRESS,))]


def _react(run: Run, content: Reaction) -> list[Effect]:
    if run.comment_id is None:
        return []
    # React before removing 👀, so that the command never shows no state.
    effects: list[Effect] = [React(comment_id=run.comment_id, content=content)]
    if run.eyes is not None:
        effects.append(Unreact(comment_id=run.comment_id, reaction_id=run.eyes))
    return effects


def plan(run: Run, needs: Needs, step: FailedStep | None) -> list[Effect]:
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
        effects += _report_failure(run, needs, step or FailedStep("unknown step"))
    # A queued or continued spec keeps the command's reaction until it ends.
    if needs.queue:
        return [*effects, *_queue(run), *_release(run)]
    if needs.spec and needs.sha and not needs.last_run:
        return [*effects, *_dispatch_next_run(run)]
    # A PR run has no outcome: its work is done when its implement job succeeds.
    outcome = "done" if run.on_pr else needs.outcome
    done = not needs.refusal and needs.implemented and outcome == "done"
    reaction = Reaction.ROCKET if done else Reaction.CONFUSED
    return [*effects, *_release(run), *_react(run, reaction)]


def plan_failure(run: Run, needs: Needs, failed: str) -> list[Effect]:
    """Return the writes that report and release the ticket after `failed` failed."""
    return [
        *_report_failure(run, needs, FailedStep(f"finish{_STEP_SEPARATOR}{failed}")),
        *_release(run),
        *_react(run, Reaction.CONFUSED),
    ]


def _finished(env: Mapping[str, str]) -> Run:
    repository = env["GH_REPO"]
    comment_id = env.get("AFK_COMMENT_ID", "")
    return Run(
        workflow=Workflow(env["AFK_WORKFLOW"]),
        number=int(env["AFK_TICKET"]),
        comment_id=int(comment_id) if comment_id else None,
        url=f"{env['GITHUB_SERVER_URL']}/{repository}/actions/runs/"
        f"{env['GITHUB_RUN_ID']}",
    )


def _read_failed_step(gh: Runner, env: Mapping[str, str]) -> FailedStep | None:
    endpoint = (
        f"repos/{env['GH_REPO']}/actions/runs/{env['GITHUB_RUN_ID']}"
        f"/attempts/{env['GITHUB_RUN_ATTEMPT']}/jobs?per_page=100"
    )
    step = failed_step(json.loads(run_gh(gh, env, Token.WORKFLOW, ["api", endpoint])))
    if step is None:
        return None
    # A job's id is its check run's id.
    annotations = (
        f"repos/{env['GH_REPO']}/check-runs/{step.job_id}/annotations?per_page=100"
    )
    errors = job_errors(
        json.loads(run_gh(gh, env, Token.WORKFLOW, ["api", annotations]))
    )
    return replace(step, errors=errors)


def run(gh: Runner, env: Mapping[str, str], writer: Writer) -> None:
    """Make the run's last writes; after a failed one, report and release the ticket."""
    finished = _finished(env)
    needs = Needs.parse(json.loads(env["AFK_NEEDS"]), finished.workflow)
    doing = "Read the failed step"
    try:
        step = _read_failed_step(gh, env) if needs.failed else None
        if finished.comment_id is not None:
            doing = "Read the App's eyes reaction"
            eyes = read_own_reaction(gh, env, finished.comment_id, Reaction.EYES)
            finished = replace(finished, eyes=eyes)
        for effect in plan(finished, needs, step):
            doing = type(effect).__name__
            writer.write(effect)
    except subprocess.CalledProcessError:
        for effect in plan_failure(finished, needs, doing):
            writer.write(effect)
        raise
