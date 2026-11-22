"""Decide whether an AFK run on a ticket refuses, queues or proceeds."""

import json
import re
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from afk.effects import EditLabels
from afk.labels import Label
from afk.writer import Runner, Token, Writer

_ASCII_LOWERCASE = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
_SLUG_SEPARATOR = re.compile(r"[^a-z0-9]+")


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
class PullRequest:
    """An open pull request whose body mentions a ticket."""

    url: str
    body: str


@dataclass(frozen=True)
class State:
    """What the shell read about the ticket or spec; a spec has child tickets."""

    ticket: Ticket
    child_tickets: Sequence[Ticket] = ()
    open_blocker_urls: Mapping[int, Sequence[str]] = field(default_factory=dict)
    pull_requests: Sequence[PullRequest] = ()


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


def pull_requests(response: list[dict[str, Any]]) -> list[PullRequest]:
    """Return the pull requests from `gh pr list`."""
    return [PullRequest(url=pr["url"], body=pr["body"]) for pr in response]


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
    slug = _SLUG_SEPARATOR.sub("-", title.translate(_ASCII_LOWERCASE))
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
    last_run: bool | None = None

    def outputs(self) -> dict[str, str]:
        """Return the check job's step outputs, leaving out what is not decided."""
        child_ticket = None if self.child_ticket is None else str(self.child_ticket)
        last_run = None if self.last_run is None else str(self.last_run).lower()
        outputs = {
            "url": self.url,
            "refusal": self.refusal,
            "block": "true" if self.block else None,
            "queue": "true" if self.queue else None,
            "spec": "true" if self.spec else None,
            "child-ticket": child_ticket,
            "child-ticket-url": self.child_ticket_url,
            "branch": self.branch,
            "last-run": last_run,
        }
        return {name: value for name, value in outputs.items() if value is not None}


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


def _closing_pull_request(state: State) -> str | None:
    number = state.ticket.number
    closes = re.compile(rf"(closes|fixes|resolves)\s+#{number}\b", re.IGNORECASE)
    return next((pr.url for pr in state.pull_requests if closes.search(pr.body)), None)


def check(run_id: str, state: State) -> CheckResult:
    """Decide whether an AFK run on the ticket is refused, queued or goes ahead."""
    result = _check_ticket(run_id, state)
    # A spec's own PR closes it while its child tickets run.
    if result.spec or result.refusal is not None:
        return result
    pull_request = _closing_pull_request(state)
    if pull_request is None:
        return result
    return replace(
        result,
        refusal=f"Refused to run: PR {pull_request} already targets this ticket. "
        "Close it first, then comment `/afk implement` again.",
    )


def _read(gh: Runner, env: Mapping[str, str], *args: str) -> str:
    return gh(["gh", *args], {**env, "GH_TOKEN": env[Token.WORKFLOW]})


def _read_state(gh: Runner, env: Mapping[str, str], number: int) -> State:
    issues = f"repos/{env['GH_REPO']}/issues"
    issue = _read(gh, env, "api", f"{issues}/{number}")
    sub_issues = _read(gh, env, "api", f"{issues}/{number}/sub_issues?per_page=100")
    children = [ticket(child) for child in json.loads(sub_issues)]
    blockers: dict[int, tuple[str, ...]] = {}
    for child in blocked_child_tickets(children):
        endpoint = f"{issues}/{child}/dependencies/blocked_by?per_page=100"
        blockers[child] = open_blocker_urls(json.loads(_read(gh, env, "api", endpoint)))
    search = f'in:body "#{number}"'
    prs = _read(
        gh,
        env,
        "pr",
        "list",
        "--state",
        "open",
        "--search",
        search,
        "--json",
        "url,body",
    )
    return State(
        ticket(json.loads(issue)),
        children,
        blockers,
        pull_requests(json.loads(prs)),
    )


def run(gh: Runner, env: Mapping[str, str], writer: Writer) -> None:
    """Mark the ticket in progress, then decide whether its AFK run goes ahead."""
    number = int(env["AFK_TICKET"])
    writer.write(EditLabels(number=number, add=(Label.IN_PROGRESS,)))
    result = check(env["GITHUB_RUN_ID"], _read_state(gh, env, number))
    for name, value in result.outputs().items():
        writer.set_output(name, value)
