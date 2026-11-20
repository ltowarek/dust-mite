"""Promote the queued tickets and specs that a closed blocking ticket unblocks."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from afk.effects import Comment, DispatchWorkflow, Effect, ReplaceLabel
from afk.writer import AS_WORKFLOW, Runner, Writer

QUEUED = "afk:queued"
IN_PROGRESS = "afk:in-progress"
BLOCKED = "afk:blocked"
COMMAND_MARKER = re.compile(r"<!-- afk-command: ([0-9]+) -->")
BLOCKING_QUERY = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    issue(number: $number) {
      blocking(first: 100) {
        nodes {
          number
          state
          repository { nameWithOwner }
          parent { number labels(first: 100) { nodes { name } } }
          labels(first: 100) { nodes { name } }
          blockedBy(first: 100) { nodes { state } }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class Promotion:
    """A ticket or spec to start an AFK run on."""

    number: int


@dataclass(frozen=True)
class Refusal:
    """A queued child ticket, which runs only through its spec."""

    number: int
    parent: int


def _labels(node: dict[str, Any]) -> set[str]:
    return {label["name"] for label in node["labels"]["nodes"]}


def _waiting(labels: set[str]) -> bool:
    return QUEUED in labels and IN_PROGRESS not in labels


def _decide(node: dict[str, Any]) -> Promotion | Refusal | None:
    unblocked = all(b["state"] != "OPEN" for b in node["blockedBy"]["nodes"])
    parent = node["parent"]
    if _waiting(_labels(node)):
        if parent is not None:
            return Refusal(number=node["number"], parent=parent["number"])
        return Promotion(number=node["number"]) if unblocked else None
    if parent is not None and _waiting(_labels(parent)) and unblocked:
        return Promotion(number=parent["number"])
    return None


def select(response: dict[str, Any], repository: str) -> list[Promotion | Refusal]:
    """Return each queued ticket or spec that the blocking ticket unblocks, once."""
    nodes = response["data"]["repository"]["issue"]["blocking"]["nodes"]
    selected: dict[int, Promotion | Refusal] = {}
    for node in nodes:
        if node["state"] != "OPEN" or node["repository"]["nameWithOwner"] != repository:
            continue
        decision = _decide(node)
        if decision is not None:
            selected.setdefault(decision.number, decision)
    return [selected[number] for number in sorted(selected)]


def command_id(comments: list[dict[str, Any]], bot_id: int) -> str | None:
    """Return the AFK command id from the App's latest queued comment."""
    found = None
    for comment in comments:
        match = COMMAND_MARKER.search(comment["body"])
        if comment["user"]["id"] == bot_id and match is not None:
            found = match.group(1)
    return found


def _refuse(refusal: Refusal) -> list[Effect]:
    parent = refusal.parent
    return [
        ReplaceLabel(number=refusal.number, remove=QUEUED, add=BLOCKED),
        Comment(
            number=refusal.number,
            body=f"Refused to promote: this ticket is a child ticket of #{parent}. "
            "Child tickets run only through their spec; comment `/afk implement` "
            f"on #{parent} instead.",
        ),
    ]


def _promote(
    promotion: Promotion, command: str | None, blocking_ticket: int
) -> list[Effect]:
    inputs = {"number": str(promotion.number)}
    if command is not None:
        inputs["comment-id"] = command
    # Dispatch first: a failed dispatch leaves the ticket queued, not stale in progress.
    return [
        DispatchWorkflow(workflow="afk-run.yml", inputs=inputs),
        ReplaceLabel(number=promotion.number, remove=QUEUED, add=IN_PROGRESS),
        Comment(
            number=promotion.number,
            body=f"Unblocked by #{blocking_ticket} closing; promoted from "
            f"`{QUEUED}` to `{IN_PROGRESS}`.",
        ),
    ]


def plan(
    selection: list[Promotion | Refusal],
    commands: Mapping[int, str | None],
    blocking_ticket: int,
) -> list[Effect]:
    """Return the writes for each selected ticket or spec, in order."""
    effects: list[Effect] = []
    for selected in selection:
        if isinstance(selected, Refusal):
            effects += _refuse(selected)
        else:
            effects += _promote(
                selected, commands.get(selected.number), blocking_ticket
            )
    return effects


def run(gh: Runner, env: Mapping[str, str]) -> dict[str, str]:
    """Read the blocking ticket's blocked tickets, then promote or refuse them."""
    repository = env["GH_REPO"]
    blocking_ticket = int(env["AFK_BLOCKING_TICKET"])
    owner, name = repository.split("/")
    read_env = {**env, "GH_TOKEN": env[AS_WORKFLOW]}
    blocking = gh(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={BLOCKING_QUERY}",
            "-f",
            f"owner={owner}",
            "-f",
            f"repo={name}",
            "-F",
            f"number={blocking_ticket}",
        ],
        read_env,
    )
    selection = select(json.loads(blocking), repository)
    commands: dict[int, str | None] = {}
    for promotion in selection:
        if isinstance(promotion, Promotion):
            endpoint = (
                f"repos/{repository}/issues/{promotion.number}/comments?per_page=100"
            )
            pages = json.loads(
                gh(["gh", "api", "--paginate", "--slurp", endpoint], read_env)
            )
            comments = [comment for page in pages for comment in page]
            commands[promotion.number] = command_id(comments, int(env["AFK_BOT_ID"]))
    writer = Writer(gh, env)
    for effect in plan(selection, commands, blocking_ticket):
        writer(effect)
    return writer.outputs()
