"""Decide whether an AFK run on a ticket refuses, queues or proceeds."""

import json
import re
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from typing import Any

from afk.effects import EditLabels
from afk.github import Token, read_graphql, run_gh
from afk.labels import Label
from afk.runner import Runner
from afk.writer import Writer

_SLUG_SEPARATOR = re.compile(r"[^a-z0-9]+")
_CLOSING_PULL_REQUESTS_QUERY = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    issue(number: $number) {
      closedByPullRequestsReferences(first: 100) { nodes { url state } }
    }
  }
}
"""


@dataclass(frozen=True)
class Ticket:
    """A ticket on the tracker; a spec is a ticket with child tickets."""

    number: int
    url: str
    title: str
    open: bool
    parent: int | None
    open_blocking_tickets: int


@dataclass(frozen=True)
class State:
    """What the shell read about the ticket or spec; a spec has child tickets."""

    ticket: Ticket
    child_tickets: Sequence[Ticket] = ()
    open_blocker_urls: Mapping[int, Sequence[str]] = field(default_factory=dict)
    closing_pull_requests: Sequence[str] = ()


def ticket(issue: dict[str, Any]) -> Ticket:
    """Return a ticket from the issues API."""
    # The API leaves out parent_issue_url for a ticket without a parent.
    parent = issue.get("parent_issue_url")
    return Ticket(
        number=issue["number"],
        url=issue["html_url"],
        title=issue["title"],
        open=issue["state"] == "open",
        parent=None if parent is None else int(parent.rsplit("/", 1)[1]),
        open_blocking_tickets=issue["issue_dependencies_summary"]["blocked_by"],
    )


def open_blocker_urls(response: list[dict[str, Any]]) -> tuple[str, ...]:
    """Return the URLs of a ticket's open blocking tickets from the API."""
    return tuple(i["html_url"] for i in response if i["state"] == "open")


def open_closing_pull_requests(response: dict[str, Any]) -> tuple[str, ...]:
    """Return the URLs of the open PRs that close the ticket, from the query."""
    issue = response["data"]["repository"]["issue"]
    nodes = issue["closedByPullRequestsReferences"]["nodes"]
    return tuple(node["url"] for node in nodes if node["state"] == "OPEN")


def _open(children: Sequence[Ticket]) -> list[Ticket]:
    return [c for c in children if c.open]


def _frontier(open_children: Sequence[Ticket]) -> list[Ticket]:
    return [c for c in open_children if not c.open_blocking_tickets]


def blocked_child_tickets(children: Sequence[Ticket]) -> list[int]:
    """Return the open child tickets whose blockers decide a spec with no frontier."""
    open_children = _open(children)
    if _frontier(open_children):
        return []
    return [c.number for c in open_children]


def _slug(title: str) -> str:
    lowercase = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
    slug = _SLUG_SEPARATOR.sub("-", title.translate(lowercase))
    return slug.removeprefix("-")[:50].removesuffix("-")


def _block_only_each_other(
    open_children: Sequence[Ticket],
    open_blocker_urls: Mapping[int, Sequence[str]],
) -> bool:
    # URLs, not numbers: a blocking ticket can live in another repository.
    urls = {c.url for c in open_children}
    return all(
        url in urls for c in open_children for url in open_blocker_urls[c.number]
    )


@dataclass(frozen=True)
class CheckResult:
    """Whether an AFK run is refused, queued or goes ahead, and on which branch."""

    url: str
    refusal: str | None = None
    block: bool = False
    queue: bool = False
    spec: bool = False
    child_ticket: int | None = None
    child_ticket_url: str | None = None
    branch: str | None = None
    last_run: bool = False


def outputs(result: CheckResult) -> dict[str, str]:
    """Return the check job's step outputs; a false or unset field sets none."""
    return {
        f.name.replace("_", "-"): "true" if value is True else str(value)
        for f in fields(result)
        if (value := getattr(result, f.name)) is not None and value is not False
    }


def _check_spec(state: State) -> CheckResult:
    url = state.ticket.url
    open_children = _open(state.child_tickets)
    if not open_children:
        return CheckResult(
            url=url,
            refusal="Refused to run: every child ticket of this spec is closed, so "
            "there is nothing to implement.",
        )
    frontier = _frontier(open_children)
    if not frontier:
        if not _block_only_each_other(open_children, state.open_blocker_urls):
            return CheckResult(url=url, queue=True)
        return CheckResult(
            url=url,
            refusal="Refused to run: the open child tickets of this spec block "
            "only each other, so none can start. Remove a blocking link from the "
            "loop, then comment `/afk implement` again.",
            block=True,
        )
    return CheckResult(
        url=url,
        spec=True,
        child_ticket=frontier[0].number,
        child_ticket_url=frontier[0].url,
        branch=f"agent/prd-{state.ticket.number}-{_slug(state.ticket.title)}",
        last_run=len(open_children) == 1,
    )


def _check_ticket(run_id: str, state: State) -> CheckResult:
    ticket = state.ticket
    if ticket.parent is None and ticket.open_blocking_tickets:
        return CheckResult(
            url=ticket.url,
            refusal="Refused to run: this ticket has an open blocking ticket. "
            "Comment `/afk implement` to queue it until its last blocking ticket "
            "closes.",
        )
    if state.child_tickets:
        return _check_spec(state)
    result = CheckResult(
        url=ticket.url, branch=f"afk/issue-{ticket.number}-{run_id}", last_run=True
    )
    if ticket.parent is None:
        return result
    return replace(
        result,
        refusal=f"Refused to run: this ticket is a child ticket of #{ticket.parent}. "
        f"Child tickets run only through their spec; comment `/afk implement` on "
        f"#{ticket.parent} instead.",
        block=True,
    )


def check(run_id: str, state: State) -> CheckResult:
    """Decide whether an AFK run on the ticket is refused, queued or goes ahead."""
    result = _check_ticket(run_id, state)
    # A spec's own PR closes it while its child tickets run.
    if result.spec or result.refusal is not None or not state.closing_pull_requests:
        return result
    return replace(
        result,
        refusal=f"Refused to run: PR {state.closing_pull_requests[0]} already targets "
        "this ticket. Close it first, then comment `/afk implement` again.",
    )


def _read_state(gh: Runner, env: Mapping[str, str], number: int) -> State:
    issues = f"repos/{env['GH_REPO']}/issues"
    issue = run_gh(gh, env, Token.WORKFLOW, ["api", f"{issues}/{number}"])
    sub_issues = run_gh(
        gh, env, Token.WORKFLOW, ["api", f"{issues}/{number}/sub_issues?per_page=100"]
    )
    children = [ticket(child) for child in json.loads(sub_issues)]
    blockers: dict[int, tuple[str, ...]] = {}
    for child in blocked_child_tickets(children):
        endpoint = f"{issues}/{child}/dependencies/blocked_by?per_page=100"
        response = run_gh(gh, env, Token.WORKFLOW, ["api", endpoint])
        blockers[child] = open_blocker_urls(json.loads(response))
    closing = read_graphql(gh, env, _CLOSING_PULL_REQUESTS_QUERY, number)
    return State(
        ticket(json.loads(issue)),
        children,
        blockers,
        open_closing_pull_requests(closing),
    )


def run(gh: Runner, env: Mapping[str, str], writer: Writer) -> None:
    """Mark the ticket in progress, then decide whether its AFK run goes ahead."""
    number = int(env["AFK_TICKET"])
    writer.write(EditLabels(number=number, add=(Label.IN_PROGRESS,)))
    result = check(env["GITHUB_RUN_ID"], _read_state(gh, env, number))
    for name, value in outputs(result).items():
        writer.set_output(name, value)
