"""Refuse, queue or dispatch an AFK command, and release its target after a failure."""

import json
import string
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from afk.effects import (
    Comment,
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

_BLOCKERS_QUERY = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    issue(number: $number) { blockedBy(first: 100) { nodes { number state } } }
  }
}
"""


class Verb(StrEnum):
    """An AFK command's verb."""

    IMPLEMENT = "implement"
    UPDATE_BRANCH = "update-branch"
    UNKNOWN = "unknown"


def parse(body: str) -> Verb | None:
    """Return the verb of the comment's first line, or None if it is no command."""
    line = body.split("\n", 1)[0].rstrip(string.whitespace)
    match line:
        case "/afk implement":
            return Verb.IMPLEMENT
        case "/afk update-branch":
            return Verb.UPDATE_BRANCH
        case _ if line == "/afk" or line.startswith("/afk "):
            return Verb.UNKNOWN
        case _:
            return None


class Kind(StrEnum):
    """Whether the command's target is an issue or a pull request."""

    ISSUE = "issue"
    PR = "pr"


@dataclass(frozen=True)
class Issue:
    """The command's target as the issues API returns it, a pull request included."""

    kind: Kind
    labels: frozenset[str]


@dataclass(frozen=True)
class Target:
    """The issue or pull request that a command runs on, and the command's comment."""

    number: int
    comment_id: int


@dataclass(frozen=True)
class State:
    """What the shell read about a target that no label refuses."""

    open_blockers: tuple[int, ...] = ()
    head_sha: str | None = None


@dataclass(frozen=True)
class Refusal:
    """Refuse the command with a reply."""

    body: str


@dataclass(frozen=True)
class Queue:
    """Queue the ticket until its open blocking tickets close."""

    blockers: tuple[int, ...]


@dataclass(frozen=True)
class Accept:
    """Start the AFK run that the command asks for."""

    workflow: str
    head_sha: str | None


def issue(response: dict[str, Any]) -> Issue:
    """Return the target's kind and labels from the issues API."""
    kind = Kind.PR if "pull_request" in response else Kind.ISSUE
    return Issue(kind=kind, labels=frozenset(lb["name"] for lb in response["labels"]))


def open_blockers(response: dict[str, Any]) -> tuple[int, ...]:
    """Return the ticket's open blocking tickets from the blockers query."""
    nodes = response["data"]["repository"]["issue"]["blockedBy"]["nodes"]
    return tuple(node["number"] for node in nodes if node["state"] == "OPEN")


def _workflow(verb: Verb, kind: Kind) -> str:
    if verb is Verb.UPDATE_BRANCH:
        return "afk-update-branch.yml"
    return "afk-run-pr.yml" if kind is Kind.PR else "afk-run.yml"


def refusal(labels: frozenset[str]) -> Refusal | None:
    """Refuse a target that is in progress or queued, before any other read."""
    if Label.IN_PROGRESS in labels:
        return Refusal(
            "Refused: an AFK run is already queued or running here "
            f"(`{Label.IN_PROGRESS}`)."
        )
    if Label.QUEUED in labels:
        return Refusal(
            f"Refused: this ticket is waiting (`{Label.QUEUED}`) and starts when it "
            "is unblocked."
        )
    return None


def decide(verb: Verb, kind: Kind, state: State) -> Queue | Accept:
    """Decide whether a known command on a target no label refuses is queued."""
    if verb is Verb.IMPLEMENT and kind is Kind.ISSUE and state.open_blockers:
        return Queue(blockers=state.open_blockers)
    return Accept(workflow=_workflow(verb, kind), head_sha=state.head_sha)


def _accept(target: Target, accept: Accept) -> list[Effect]:
    inputs = {"number": str(target.number), "comment-id": str(target.comment_id)}
    if accept.head_sha is not None:
        inputs["head-sha"] = accept.head_sha
    return [
        React(comment_id=target.comment_id, content=Reaction.EYES),
        EditLabels(
            number=target.number, add=(Label.IN_PROGRESS,), remove=(Label.BLOCKED,)
        ),
        DispatchWorkflow(workflow=accept.workflow, inputs=inputs),
    ]


def _queue(target: Target, queue: Queue) -> list[Effect]:
    blockers = ", ".join(f"#{number}" for number in queue.blockers)
    # The marker carries the command to the run that promote-queued dispatches.
    return [
        React(comment_id=target.comment_id, content=Reaction.EYES),
        EditLabels(number=target.number, add=(Label.QUEUED,), remove=(Label.BLOCKED,)),
        Comment(
            number=target.number,
            body=f"Queued (`{Label.QUEUED}`) until its blocking tickets close: "
            f"{blockers}. The AFK run starts when the last one closes. "
            f"<!-- afk-command: {target.comment_id} -->",
        ),
    ]


def plan(target: Target, decision: Refusal | Queue | Accept) -> list[Effect]:
    """Return the writes that carry out a decision, in order."""
    match decision:
        case Refusal(body=body):
            return [
                Comment(number=target.number, body=body),
                React(comment_id=target.comment_id, content=Reaction.CONFUSED),
            ]
        case Queue():
            return _queue(target, decision)
        case Accept():
            return _accept(target, decision)


def release(target: Target, *, accepted: bool) -> list[Effect]:
    """Return the writes that release a target after the command's job failed."""
    # Only an accepted command added afk:in-progress; otherwise another run owns it.
    effects: list[Effect] = []
    if accepted:
        effects.append(EditLabels(number=target.number, remove=(Label.IN_PROGRESS,)))
    effects.append(React(comment_id=target.comment_id, content=Reaction.CONFUSED))
    return effects


def _target(env: Mapping[str, str]) -> Target:
    return Target(number=int(env["AFK_NUMBER"]), comment_id=int(env["AFK_COMMENT_ID"]))


def _read_issue(gh: Runner, env: Mapping[str, str]) -> Issue:
    # Read now, not from the event: an earlier command may have changed the labels.
    endpoint = f"repos/{env['GH_REPO']}/issues/{env['AFK_NUMBER']}"
    return issue(json.loads(run_gh(gh, env, Token.APP, ["api", endpoint])))


def _read_state(gh: Runner, env: Mapping[str, str], verb: Verb, kind: Kind) -> State:
    repository = env["GH_REPO"]
    number = env["AFK_NUMBER"]
    blockers: tuple[int, ...] = ()
    if verb is Verb.IMPLEMENT and kind is Kind.ISSUE:
        owner, name = repository.split("/")
        response = run_gh(
            gh,
            env,
            Token.APP,
            [
                "api",
                "graphql",
                "-f",
                f"query={_BLOCKERS_QUERY}",
                "-f",
                f"owner={owner}",
                "-f",
                f"repo={name}",
                "-F",
                f"number={number}",
            ],
        )
        blockers = open_blockers(json.loads(response))
    head_sha = None
    if kind is Kind.PR:
        pr = run_gh(gh, env, Token.APP, ["pr", "view", number, "--json", "headRefOid"])
        head_sha = json.loads(pr)["headRefOid"]
    return State(open_blockers=blockers, head_sha=head_sha)


def run(gh: Runner, env: Mapping[str, str], writer: Writer) -> None:
    """Refuse, queue or dispatch the AFK command in `AFK_BODY`."""
    target = _target(env)
    effects: list[Effect] = []
    match parse(env["AFK_BODY"]):
        case None:
            pass
        case Verb.UNKNOWN:
            unknown = (
                "Unknown AFK command. The first line of the comment must be "
                "`/afk implement` or `/afk update-branch`."
            )
            effects = plan(target, Refusal(unknown))
        case verb:
            target_issue = _read_issue(gh, env)
            kind = target_issue.kind
            decision = refusal(target_issue.labels) or decide(
                verb, kind, _read_state(gh, env, verb, kind)
            )
            if isinstance(decision, Accept):
                # Set before the writes, so that the release step sees it if one fails.
                writer.set_output("accepted", "true")
            effects = plan(target, decision)
    for effect in effects:
        writer.write(effect)


def run_release(_gh: Runner, env: Mapping[str, str], writer: Writer) -> None:
    """Release the command's target after its job failed."""
    for effect in release(_target(env), accepted=env["AFK_ACCEPTED"] == "true"):
        writer.write(effect)
