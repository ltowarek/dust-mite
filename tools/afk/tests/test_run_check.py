"""Guards whether an AFK run refuses, queues or proceeds, and on which branch."""

from dataclasses import dataclass, field

import pytest

from afk.run_check import BlockingTicket, ChildTicket, PullRequest, Ticket, check

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


class TestCheck:
    def test_runs_a_plain_ticket_on_its_own_branch_in_one_run(self) -> None:
        reader = ReaderStub(ticket())

        assert check(7, RUN_ID, reader) == {
            "url": f"{URL}/7",
            "branch": "afk/issue-7-4242",
            "last-run": "true",
        }

    def test_refuses_a_ticket_with_an_open_blocking_ticket(self) -> None:
        reader = ReaderStub(ticket(open_blocking_tickets=1))

        assert check(7, RUN_ID, reader) == {
            "url": f"{URL}/7",
            "refusal": "Refused to run: this ticket has an open blocking ticket. "
            "Comment `/afk implement` to queue it until its last blocking ticket "
            "closes.",
        }

    def test_refuses_and_blocks_a_child_ticket_even_when_it_is_blocked(self) -> None:
        reader = ReaderStub(ticket(parent=3, open_blocking_tickets=1))

        assert check(7, RUN_ID, reader) == {
            "url": f"{URL}/7",
            "block": "true",
            "refusal": "Refused to run: this ticket is a child ticket of #3. Child "
            "tickets run only through their spec; comment `/afk implement` on #3 "
            "instead.",
            "branch": "afk/issue-7-4242",
            "last-run": "true",
        }

    def test_refuses_a_spec_whose_child_tickets_are_all_closed(self) -> None:
        reader = ReaderStub(
            ticket(child_tickets=2),
            [child(8, is_open=False), child(9, is_open=False)],
        )

        assert check(7, RUN_ID, reader) == {
            "url": f"{URL}/7",
            "refusal": "Refused to run: every child ticket of this spec is closed, so "
            "there is nothing to implement.",
        }

    def test_runs_a_spec_s_first_unblocked_open_child_ticket_on_the_spec_s_branch(
        self,
    ) -> None:
        reader = ReaderStub(
            ticket(title="Fix the thing", child_tickets=4),
            [child(8, is_open=False), child(9, blocked_by=1), child(10), child(11)],
        )

        assert check(7, RUN_ID, reader) == {
            "url": f"{URL}/7",
            "spec": "true",
            "child-ticket": "10",
            "child-ticket-url": f"{URL}/10",
            "branch": "agent/prd-7-fix-the-thing",
            "last-run": "false",
        }

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

        assert check(7, RUN_ID, reader)["branch"] == branch

    def test_marks_the_run_on_a_spec_s_last_open_child_ticket_as_its_last_run(
        self,
    ) -> None:
        reader = ReaderStub(
            ticket(child_tickets=2), [child(8, is_open=False), child(9)]
        )

        assert check(7, RUN_ID, reader)["last-run"] == "true"

    def test_refuses_and_blocks_a_spec_whose_open_child_tickets_block_only_each_other(
        self,
    ) -> None:
        reader = ReaderStub(
            ticket(child_tickets=2),
            [child(8, blocked_by=1), child(9, blocked_by=1)],
            blocking={
                8: [blocking(9), blocking(50, is_open=False)],
                9: [blocking(8)],
            },
        )

        assert check(7, RUN_ID, reader) == {
            "url": f"{URL}/7",
            "block": "true",
            "refusal": "Refused to run: the open child tickets of this spec block only "
            "each other, so none can start. Remove a blocking link from the loop, then "
            "comment `/afk implement` again.",
        }

    def test_queues_a_spec_whose_open_child_tickets_wait_on_another_ticket(
        self,
    ) -> None:
        reader = ReaderStub(
            ticket(child_tickets=2),
            [child(8, blocked_by=1), child(9, blocked_by=1)],
            blocking={8: [blocking(9)], 9: [blocking(50)]},
        )

        assert check(7, RUN_ID, reader) == {"url": f"{URL}/7", "queue": "true"}

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param("Closes #7", id="closes"),
            pytest.param("Some text.\n\nfixes\n#7.", id="fixes on the next line"),
            pytest.param("RESOLVES #7", id="resolves in capitals"),
        ],
    )
    def test_refuses_a_ticket_that_an_open_pr_closes(self, body: str) -> None:
        reader = ReaderStub(
            ticket(),
            pull_requests=[
                PullRequest(url="https://github.com/owner/repo/pull/20", body="#7"),
                PullRequest(url="https://github.com/owner/repo/pull/21", body=body),
            ],
        )

        assert check(7, RUN_ID, reader) == {
            "url": f"{URL}/7",
            "refusal": "Refused to run: PR https://github.com/owner/repo/pull/21 "
            "already targets this ticket. Close it first, then comment "
            "`/afk implement` again.",
            "branch": "afk/issue-7-4242",
            "last-run": "true",
        }

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param("Refs #7", id="refers to the ticket"),
            pytest.param("Closes #70", id="closes a longer number"),
            pytest.param("Closes#7", id="has no space before the number"),
        ],
    )
    def test_runs_a_ticket_that_an_open_pr_only_mentions(self, body: str) -> None:
        reader = ReaderStub(
            ticket(),
            pull_requests=[
                PullRequest(url="https://github.com/owner/repo/pull/20", body=body)
            ],
        )

        assert "refusal" not in check(7, RUN_ID, reader)

    def test_runs_a_spec_s_child_ticket_while_an_open_pr_closes_the_spec(
        self,
    ) -> None:
        reader = ReaderStub(
            ticket(child_tickets=1),
            [child(8)],
            pull_requests=[
                PullRequest(
                    url="https://github.com/owner/repo/pull/20", body="Closes #7"
                )
            ],
        )

        assert "refusal" not in check(7, RUN_ID, reader)

    def test_queues_and_refuses_a_spec_that_an_open_pr_closes(self) -> None:
        reader = ReaderStub(
            ticket(child_tickets=1),
            [child(8, blocked_by=1)],
            blocking={8: [blocking(50)]},
            pull_requests=[
                PullRequest(
                    url="https://github.com/owner/repo/pull/20", body="Closes #7"
                )
            ],
        )

        assert check(7, RUN_ID, reader) == {
            "url": f"{URL}/7",
            "queue": "true",
            "refusal": "Refused to run: PR https://github.com/owner/repo/pull/20 "
            "already targets this ticket. Close it first, then comment "
            "`/afk implement` again.",
        }
