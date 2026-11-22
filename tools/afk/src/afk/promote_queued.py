"""Promote the queued tickets and specs that a closed blocking ticket unblocks."""

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from afk.effects import Comment, DispatchWorkflow, EditLabels, Effect
from afk.labels import Label
from afk.writer import Runner, Token, Writer

logger = logging.getLogger(__name__)
_COMMAND_MARKER = re.compile(r"<!-- afk-command: ([0-9]*) -->")
_BLOCKING_QUERY = """
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
    return Label.QUEUED in labels and Label.IN_PROGRESS not in labels


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


def command_id(pages: list[list[dict[str, Any]]], bot_id: int) -> str | None:
    """Return the AFK command id from the App's latest queued comment."""
    found = None
    for comment in (comment for page in pages for comment in page):
        match = _COMMAND_MARKER.search(comment["body"])
        if comment["user"]["id"] == bot_id and match is not None:
            found = match.group(1) or None
    return found


def _refuse(refusal: Refusal) -> list[Effect]:
    parent = refusal.parent
    return [
        EditLabels(number=refusal.number, add=(Label.BLOCKED,), remove=(Label.QUEUED,)),
        Comment(
            number=refusal.number,
            body=f"Refused to promote: this ticket is a child ticket of #{parent}. "
            "Child tickets run only through their spec; comment `/afk implement` "
            f"on #{parent} instead.",
        ),
    ]


def _promote(
    promotion: Promotion, command_id: str | None, blocking_ticket: int
) -> list[Effect]:
    inputs = {"number": str(promotion.number)}
    if command_id is not None:
        inputs["comment-id"] = command_id
    # Dispatch first: a failed dispatch leaves the ticket queued, not stale in progress.
    return [
        DispatchWorkflow(workflow="afk-run.yml", inputs=inputs),
        EditLabels(
            number=promotion.number, add=(Label.IN_PROGRESS,), remove=(Label.QUEUED,)
        ),
        Comment(
            number=promotion.number,
            body=f"Unblocked by #{blocking_ticket} closing; promoted from "
            f"`{Label.QUEUED}` to `{Label.IN_PROGRESS}`.",
        ),
    ]


def _effects(
    selected: Promotion | Refusal, command_id: str | None, blocking_ticket: int
) -> list[Effect]:
    match selected:
        case Refusal():
            return _refuse(selected)
        case Promotion():
            return _promote(selected, command_id, blocking_ticket)


def plan(
    selection: list[Promotion | Refusal],
    command_ids: Mapping[int, str | None],
    blocking_ticket: int,
) -> list[Effect]:
    """Return the writes for each selected ticket or spec, in order."""
    effects: list[Effect] = []
    for selected in selection:
        effects += _effects(selected, command_ids.get(selected.number), blocking_ticket)
    return effects


def run(gh: Runner, env: Mapping[str, str], writer: Writer) -> None:
    """Read the blocking ticket's blocked tickets, then promote or refuse them."""
    repository = env["GH_REPO"]
    blocking_ticket = int(env["AFK_BLOCKING_TICKET"])
    owner, name = repository.split("/")
    read_env = {**env, "GH_TOKEN": env[Token.WORKFLOW]}
    blocking = gh(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={_BLOCKING_QUERY}",
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
    logger.info("Selected: %s", selection)
    command_ids: dict[int, str | None] = {}
    for selected in selection:
        match selected:
            case Promotion(number=number):
                endpoint = f"repos/{repository}/issues/{number}/comments?per_page=100"
                pages = json.loads(
                    gh(["gh", "api", "--paginate", "--slurp", endpoint], read_env)
                )
                command_ids[number] = command_id(pages, int(env["AFK_BOT_ID"]))
    for effect in plan(selection, command_ids, blocking_ticket):
        writer.write(effect)
