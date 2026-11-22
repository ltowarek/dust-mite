"""Decide whether an AFK run on a ticket refuses, queues or proceeds."""

import json
import re
import string
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Protocol

from afk.effects import EditLabels
from afk.labels import Label
from afk.writer import Runner, Token, Writer

_ASCII_LOWERCASE = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
_SLUG_SEPARATOR = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Ticket:
    """The ticket or spec that an AFK run works on."""

    url: str
    title: str
    child_tickets: int
    parent: int | None
    open_blocking_tickets: int


@dataclass(frozen=True)
class ChildTicket:
    """A child ticket of a spec."""

    number: int
    url: str
    open: bool
    open_blocking_tickets: int


@dataclass(frozen=True)
class BlockingTicket:
    """A ticket that blocks another."""

    url: str
    open: bool


@dataclass(frozen=True)
class PullRequest:
    """An open pull request whose body mentions a ticket."""

    url: str
    body: str


class Reader(Protocol):
    """The tracker reads that the check makes."""

    def ticket(self, number: int) -> Ticket:
        """Return the ticket or spec."""
        ...

    def child_tickets(self, spec: int) -> list[ChildTicket]:
        """Return the spec's child tickets, in their order on the spec."""
        ...

    def blocking_tickets(self, ticket: int) -> list[BlockingTicket]:
        """Return the tickets that block `ticket`."""
        ...

    def open_pull_requests(self, ticket: int) -> list[PullRequest]:
        """Return the open pull requests whose body mentions `#ticket`."""
        ...


def _slug(title: str) -> str:
    slug = _SLUG_SEPARATOR.sub("-", title.translate(_ASCII_LOWERCASE))
    return slug.removeprefix("-")[:50].removesuffix("-")


def _block_only_each_other(
    open_child_tickets: list[ChildTicket], reader: Reader
) -> bool:
    urls = {c.url for c in open_child_tickets}
    return all(
        b.url in urls
        for c in open_child_tickets
        for b in reader.blocking_tickets(c.number)
        if b.open
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


def _check_spec(ticket: Ticket, number: int, reader: Reader) -> CheckResult:
    open_child_tickets = [c for c in reader.child_tickets(number) if c.open]
    if not open_child_tickets:
        return CheckResult(
            url=ticket.url,
            refusal="Refused to run: every child ticket of this spec is closed, so "
            "there is nothing to implement.",
        )
    frontier = [c for c in open_child_tickets if not c.open_blocking_tickets]
    if not frontier:
        if not _block_only_each_other(open_child_tickets, reader):
            return CheckResult(url=ticket.url, queue=True)
        return CheckResult(
            url=ticket.url,
            refusal="Refused to run: the open child tickets of this spec block "
            "only each other, so none can start. Remove a blocking link from the "
            "loop, then comment `/afk implement` again.",
            block=True,
        )
    return CheckResult(
        url=ticket.url,
        spec=True,
        child_ticket=frontier[0].number,
        child_ticket_url=frontier[0].url,
        branch=f"agent/prd-{number}-{_slug(ticket.title)}",
        last_run=len(open_child_tickets) == 1,
    )


def _check_ticket(number: int, run_id: str, reader: Reader) -> CheckResult:
    ticket = reader.ticket(number)
    if ticket.parent is None and ticket.open_blocking_tickets:
        return CheckResult(
            url=ticket.url,
            refusal="Refused to run: this ticket has an open blocking ticket. "
            "Comment `/afk implement` to queue it until its last blocking ticket "
            "closes.",
        )
    if ticket.child_tickets:
        return _check_spec(ticket, number, reader)
    result = CheckResult(
        url=ticket.url, branch=f"afk/issue-{number}-{run_id}", last_run=True
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


def _closing_pull_request(number: int, reader: Reader) -> str | None:
    closes = re.compile(rf"(closes|fixes|resolves)\s+#{number}\b", re.IGNORECASE)
    return next(
        (pr.url for pr in reader.open_pull_requests(number) if closes.search(pr.body)),
        None,
    )


def check(number: int, run_id: str, reader: Reader) -> CheckResult:
    """Decide whether an AFK run on `number` is refused, queued or goes ahead."""
    result = _check_ticket(number, run_id, reader)
    # A spec's own PR closes it while its child tickets run.
    if result.spec or result.refusal is not None:
        return result
    pull_request = _closing_pull_request(number, reader)
    if pull_request is None:
        return result
    return replace(
        result,
        refusal=f"Refused to run: PR {pull_request} already targets this ticket. "
        "Close it first, then comment `/afk implement` again.",
    )


class GhReader:
    """Read the tracker with `gh` and the workflow's token."""

    def __init__(self, gh: Runner, env: Mapping[str, str]) -> None:
        """Read `GH_REPO` through `gh` with the token in `AFK_WORKFLOW_TOKEN`."""
        self._gh = gh
        self._env = {**env, "GH_TOKEN": env[Token.WORKFLOW]}
        self._repository = env["GH_REPO"]

    def _read(self, *args: str) -> str:
        return self._gh(["gh", *args], self._env)

    def ticket(self, number: int) -> Ticket:
        """Return the ticket or spec."""
        view = json.loads(
            self._read(
                "issue",
                "view",
                str(number),
                "--json",
                "title,url,subIssuesSummary,parent",
            )
        )
        issue = json.loads(
            self._read("api", f"repos/{self._repository}/issues/{number}")
        )
        parent = view["parent"]
        return Ticket(
            url=view["url"],
            title=view["title"],
            child_tickets=view["subIssuesSummary"]["total"],
            parent=None if parent is None else parent["number"],
            open_blocking_tickets=issue["issue_dependencies_summary"]["blocked_by"],
        )

    def child_tickets(self, spec: int) -> list[ChildTicket]:
        """Return the spec's child tickets, in their order on the spec."""
        endpoint = f"repos/{self._repository}/issues/{spec}/sub_issues?per_page=100"
        return [
            ChildTicket(
                number=issue["number"],
                url=issue["html_url"],
                open=issue["state"] == "open",
                open_blocking_tickets=issue["issue_dependencies_summary"]["blocked_by"],
            )
            for issue in json.loads(self._read("api", endpoint))
        ]

    def blocking_tickets(self, ticket: int) -> list[BlockingTicket]:
        """Return the tickets that block `ticket`."""
        endpoint = (
            f"repos/{self._repository}/issues/{ticket}/dependencies/blocked_by"
            "?per_page=100"
        )
        return [
            BlockingTicket(url=issue["html_url"], open=issue["state"] == "open")
            for issue in json.loads(self._read("api", endpoint))
        ]

    def open_pull_requests(self, ticket: int) -> list[PullRequest]:
        """Return the open pull requests whose body mentions `#ticket`."""
        pull_requests = json.loads(
            self._read(
                "pr",
                "list",
                "--state",
                "open",
                "--search",
                f'in:body "#{ticket}"',
                "--json",
                "url,body",
            )
        )
        return [PullRequest(url=pr["url"], body=pr["body"]) for pr in pull_requests]


def run(gh: Runner, env: Mapping[str, str], writer: Writer) -> None:
    """Mark the ticket in progress, then decide whether its AFK run goes ahead."""
    number = int(env["AFK_TICKET"])
    writer.write(EditLabels(number=number, add=(Label.IN_PROGRESS,)))
    result = check(number, env["GITHUB_RUN_ID"], GhReader(gh, env))
    for name, value in result.outputs().items():
        writer.set_output(name, value)
