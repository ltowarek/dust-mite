"""Guards whether an AFK run refuses, queues or proceeds, and on which branch."""

from dataclasses import dataclass, field

import pytest

from afk.run_check import (
    BlockingTicket,
    CheckResult,
    ChildTicket,
    PullRequest,
    Ticket,
    check,
)

RUN_ID = "4242"
URL = "https://github.com/owner/repo/issues"


@dataclass
class ReaderStub:
    ticket_: Ticket
    child_tickets_: list[ChildTicket] = field(default_factory=list)
    blocking: dict[int, list[BlockingTicket]] = field(default_factory=dict)
    pull_requests: list[PullRequest] = field(default_factory=list)

    def ticket(self, _number: int) -> Ticket:
        return self.ticket_

    def child_tickets(self, _spec: int) -> list[ChildTicket]:
        return self.child_tickets_

    def blocking_tickets(self, ticket: int) -> list[BlockingTicket]:
        return self.blocking.get(ticket, [])

    def open_pull_requests(self, _ticket: int) -> list[PullRequest]:
        return self.pull_requests


def ticket(
    title: str = "Fix the thing",
    child_tickets: int = 0,
    parent: int | None = None,
    open_blocking_tickets: int = 0,
) -> Ticket:
    return Ticket(
        url=f"{URL}/7",
        title=title,
        child_tickets=child_tickets,
        parent=parent,
        open_blocking_tickets=open_blocking_tickets,
    )


def child(number: int, *, is_open: bool = True, blocked_by: int = 0) -> ChildTicket:
    return ChildTicket(
        number=number,
        url=f"{URL}/{number}",
        open=is_open,
        open_blocking_tickets=blocked_by,
    )


def blocking(number: int, *, is_open: bool = True) -> BlockingTicket:
    return BlockingTicket(url=f"{URL}/{number}", open=is_open)


def pull_request(number: int, body: str) -> PullRequest:
    return PullRequest(url=f"https://github.com/owner/repo/pull/{number}", body=body)


def pr_refusal(number: int) -> str:
    return (
        f"Refused to run: PR https://github.com/owner/repo/pull/{number} already "
        "targets this ticket. Close it first, then comment `/afk implement` again."
    )


CHILD_TICKET_REFUSAL = (
    "Refused to run: this ticket is a child ticket of #3. Child tickets run only "
    "through their spec; comment `/afk implement` on #3 instead."
)


class TestCheck:
    @pytest.mark.parametrize(
        ("reader", "result"),
        [
            pytest.param(
                ReaderStub(ticket()),
                CheckResult(url=f"{URL}/7", branch="afk/issue-7-4242", last_run=True),
                id="runs a plain ticket on its own branch in one run",
            ),
            pytest.param(
                ReaderStub(ticket(open_blocking_tickets=1)),
                CheckResult(
                    url=f"{URL}/7",
                    refusal="Refused to run: this ticket has an open blocking "
                    "ticket. Comment `/afk implement` to queue it until its last "
                    "blocking ticket closes.",
                ),
                id="refuses a ticket with an open blocking ticket",
            ),
            pytest.param(
                ReaderStub(ticket(parent=3, open_blocking_tickets=1)),
                CheckResult(
                    url=f"{URL}/7",
                    refusal=CHILD_TICKET_REFUSAL,
                    block=True,
                    branch="afk/issue-7-4242",
                    last_run=True,
                ),
                id="refuses and blocks a child ticket even when it is blocked",
            ),
            pytest.param(
                ReaderStub(
                    ticket(child_tickets=2),
                    [child(8, is_open=False), child(9, is_open=False)],
                ),
                CheckResult(
                    url=f"{URL}/7",
                    refusal="Refused to run: every child ticket of this spec is "
                    "closed, so there is nothing to implement.",
                ),
                id="refuses a spec whose child tickets are all closed",
            ),
            pytest.param(
                ReaderStub(
                    ticket(title="Fix the thing", child_tickets=4),
                    [
                        child(8, is_open=False),
                        child(9, blocked_by=1),
                        child(10),
                        child(11),
                    ],
                ),
                CheckResult(
                    url=f"{URL}/7",
                    spec=True,
                    child_ticket=10,
                    child_ticket_url=f"{URL}/10",
                    branch="agent/prd-7-fix-the-thing",
                    last_run=False,
                ),
                id="runs a spec's first unblocked open child ticket on its branch",
            ),
            pytest.param(
                ReaderStub(
                    ticket(title="Fix the thing", child_tickets=2),
                    [child(8, is_open=False), child(9)],
                ),
                CheckResult(
                    url=f"{URL}/7",
                    spec=True,
                    child_ticket=9,
                    child_ticket_url=f"{URL}/9",
                    branch="agent/prd-7-fix-the-thing",
                    last_run=True,
                ),
                id="runs a spec's last open child ticket as its last run",
            ),
            pytest.param(
                ReaderStub(
                    ticket(child_tickets=2),
                    [child(8, blocked_by=1), child(9, blocked_by=1)],
                    blocking={
                        8: [blocking(9), blocking(50, is_open=False)],
                        9: [blocking(8)],
                    },
                ),
                CheckResult(
                    url=f"{URL}/7",
                    refusal="Refused to run: the open child tickets of this spec "
                    "block only each other, so none can start. Remove a blocking link "
                    "from the loop, then comment `/afk implement` again.",
                    block=True,
                ),
                id="refuses and blocks a spec whose open child tickets block only "
                "each other",
            ),
            pytest.param(
                ReaderStub(
                    ticket(child_tickets=2),
                    [child(8, blocked_by=1), child(9, blocked_by=1)],
                    blocking={8: [blocking(9)], 9: [blocking(50)]},
                ),
                CheckResult(url=f"{URL}/7", queue=True),
                id="queues a spec whose open child tickets wait on another ticket",
            ),
            pytest.param(
                ReaderStub(
                    ticket(),
                    pull_requests=[
                        pull_request(20, "#7"),
                        pull_request(21, "Closes #7"),
                    ],
                ),
                CheckResult(
                    url=f"{URL}/7",
                    refusal=pr_refusal(21),
                    branch="afk/issue-7-4242",
                    last_run=True,
                ),
                id="refuses a ticket that the first open PR to close it names",
            ),
            pytest.param(
                ReaderStub(
                    ticket(child_tickets=1),
                    [child(8, blocked_by=1)],
                    blocking={8: [blocking(50)]},
                    pull_requests=[pull_request(20, "Closes #7")],
                ),
                CheckResult(url=f"{URL}/7", refusal=pr_refusal(20), queue=True),
                id="queues and refuses a spec that an open PR closes",
            ),
        ],
    )
    def test_decides_whether_the_run_goes_ahead(
        self, reader: ReaderStub, result: CheckResult
    ) -> None:
        assert check(7, RUN_ID, reader) == result

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param("Closes #7", id="closes"),
            pytest.param("Some text.\n\nfixes\n#7.", id="fixes on the next line"),
            pytest.param("RESOLVES #7", id="resolves in capitals"),
        ],
    )
    def test_refuses_a_ticket_that_an_open_pr_closes(self, body: str) -> None:
        reader = ReaderStub(ticket(), pull_requests=[pull_request(20, body)])

        assert check(7, RUN_ID, reader).refusal == pr_refusal(20)

    @pytest.mark.parametrize(
        "reader",
        [
            pytest.param(
                ReaderStub(ticket(), pull_requests=[pull_request(20, "Refs #7")]),
                id="refers to the ticket",
            ),
            pytest.param(
                ReaderStub(ticket(), pull_requests=[pull_request(20, "Closes #70")]),
                id="closes a longer number",
            ),
            pytest.param(
                ReaderStub(ticket(), pull_requests=[pull_request(20, "Closes#7")]),
                id="has no space before the number",
            ),
            pytest.param(
                ReaderStub(
                    ticket(child_tickets=1),
                    [child(8)],
                    pull_requests=[pull_request(20, "Closes #7")],
                ),
                id="closes the spec whose child ticket runs",
            ),
        ],
    )
    def test_runs_a_ticket_despite_an_open_pr_that(self, reader: ReaderStub) -> None:
        assert check(7, RUN_ID, reader).refusal is None

    @pytest.mark.parametrize(
        ("title", "branch"),
        [
            pytest.param(
                "  Run `afk`: the check phase!  ",
                "agent/prd-7-run-afk-the-check-phase",
                id="joins words with one hyphen and trims the ends",
            ),
            pytest.param(
                f"{'x' * 49} yz",
                f"agent/prd-7-{'x' * 49}",
                id="cuts the slug at 50 characters and trims the cut end",
            ),
            pytest.param(
                "\u212aelvin Zażółć",
                "agent/prd-7-elvin-za",
                id="lowercases only ASCII letters and drops the rest",
            ),
        ],
    )
    def test_names_a_spec_s_branch_after_its_title(
        self, title: str, branch: str
    ) -> None:
        reader = ReaderStub(ticket(title=title, child_tickets=1), [child(8)])

        assert check(7, RUN_ID, reader).branch == branch


class TestCheckResult:
    class TestOutputs:
        @pytest.mark.parametrize(
            ("result", "outputs"),
            [
                pytest.param(
                    CheckResult(url=f"{URL}/7"),
                    {"url": f"{URL}/7"},
                    id="sets only the URL when nothing else is decided",
                ),
                pytest.param(
                    CheckResult(
                        url=f"{URL}/7",
                        refusal="Refused.",
                        block=True,
                        queue=True,
                        spec=True,
                        child_ticket=10,
                        child_ticket_url=f"{URL}/10",
                        branch="agent/prd-7-fix",
                        last_run=False,
                    ),
                    {
                        "url": f"{URL}/7",
                        "refusal": "Refused.",
                        "block": "true",
                        "queue": "true",
                        "spec": "true",
                        "child-ticket": "10",
                        "child-ticket-url": f"{URL}/10",
                        "branch": "agent/prd-7-fix",
                        "last-run": "false",
                    },
                    id="writes every decided field as its step output",
                ),
                pytest.param(
                    CheckResult(url=f"{URL}/7", last_run=True),
                    {"url": f"{URL}/7", "last-run": "true"},
                    id="writes a last run as true",
                ),
            ],
        )
        def test_returns_the_check_job_s_step_outputs(
            self, result: CheckResult, outputs: dict[str, str]
        ) -> None:
            assert result.outputs() == outputs
