"""Guards whether an AFK run refuses, queues or proceeds, and on which branch."""

import json
from pathlib import Path
from typing import Any

import pytest

from afk import run_check
from afk.run_check import (
    CheckResult,
    State,
    Ticket,
    blocked_child_tickets,
    check,
    open_blocker_urls,
    open_closing_pull_requests,
    outputs,
    ticket,
)
from afk.writer import Writer
from tests.test_doubles import GhCall, GhSpy, read_outputs

RUN_ID = "4242"
URL = "https://github.com/owner/repo/issues"


def make_ticket(
    number: int = 7,
    *,
    title: str = "Fix the thing",
    is_open: bool = True,
    parent: int | None = None,
    blocked_by: int = 0,
) -> Ticket:
    return Ticket(
        number=number,
        url=f"{URL}/{number}",
        title=title,
        open=is_open,
        parent=parent,
        open_blocking_tickets=blocked_by,
    )


def make_issue(
    number: int, *, state: str = "open", blocked_by: int = 0
) -> dict[str, Any]:
    return {
        "number": number,
        "html_url": f"{URL}/{number}",
        "title": "Fix the thing",
        "state": state,
        "issue_dependencies_summary": {"blocked_by": blocked_by},
    }


PR_URL = "https://github.com/owner/repo/pull"


def make_pr_refusal(number: int) -> str:
    return (
        f"Refused to run: PR {PR_URL}/{number} already targets this ticket. "
        "Close it first, then comment `/afk implement` again."
    )


CHILD_TICKET_REFUSAL = (
    "Refused to run: this ticket is a child ticket of #3. Child tickets run only "
    "through their spec; comment `/afk implement` on #3 instead."
)


class TestCheck:
    @pytest.mark.parametrize(
        ("state", "result"),
        [
            pytest.param(
                State(make_ticket()),
                CheckResult(url=f"{URL}/7", branch="afk/issue-7-4242", last_run=True),
                id="runs a plain ticket on its own branch in one run",
            ),
            pytest.param(
                State(make_ticket(blocked_by=1)),
                CheckResult(
                    url=f"{URL}/7",
                    refusal="Refused to run: this ticket has an open blocking "
                    "ticket. Comment `/afk implement` to queue it until its last "
                    "blocking ticket closes.",
                ),
                id="refuses a ticket with an open blocking ticket",
            ),
            pytest.param(
                State(make_ticket(parent=3, blocked_by=1)),
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
                State(
                    make_ticket(),
                    [make_ticket(8, is_open=False), make_ticket(9, is_open=False)],
                ),
                CheckResult(
                    url=f"{URL}/7",
                    refusal="Refused to run: every child ticket of this spec is "
                    "closed, so there is nothing to implement.",
                ),
                id="refuses a spec whose child tickets are all closed",
            ),
            pytest.param(
                State(
                    make_ticket(title="Fix the thing"),
                    [
                        make_ticket(8, is_open=False),
                        make_ticket(9, blocked_by=1),
                        make_ticket(10),
                        make_ticket(11),
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
                State(
                    make_ticket(title="Fix the thing"),
                    [make_ticket(8, is_open=False), make_ticket(9)],
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
                State(
                    make_ticket(),
                    [make_ticket(8, blocked_by=1), make_ticket(9, blocked_by=1)],
                    open_blocker_urls={8: [f"{URL}/9"], 9: [f"{URL}/8"]},
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
                State(
                    make_ticket(),
                    [make_ticket(8, blocked_by=1), make_ticket(9, blocked_by=1)],
                    open_blocker_urls={8: [f"{URL}/9"], 9: [f"{URL}/50"]},
                ),
                CheckResult(url=f"{URL}/7", queue=True),
                id="queues a spec whose open child tickets wait on another ticket",
            ),
            pytest.param(
                State(
                    make_ticket(),
                    closing_pull_requests=[f"{PR_URL}/20", f"{PR_URL}/21"],
                ),
                CheckResult(
                    url=f"{URL}/7",
                    refusal=make_pr_refusal(20),
                    branch="afk/issue-7-4242",
                    last_run=True,
                ),
                id="refuses a ticket that an open PR closes, naming the first",
            ),
            pytest.param(
                State(
                    make_ticket(),
                    [make_ticket(8, blocked_by=1)],
                    open_blocker_urls={8: [f"{URL}/50"]},
                    closing_pull_requests=[f"{PR_URL}/20"],
                ),
                CheckResult(url=f"{URL}/7", refusal=make_pr_refusal(20), queue=True),
                id="queues and refuses a spec that an open PR closes",
            ),
        ],
    )
    def test_decides_whether_the_run_goes_ahead(
        self, state: State, result: CheckResult
    ) -> None:
        assert check(RUN_ID, state) == result

    def test_runs_a_spec_s_child_ticket_despite_the_spec_s_open_pr(self) -> None:
        state = State(
            make_ticket(), [make_ticket(8)], closing_pull_requests=[f"{PR_URL}/20"]
        )

        assert check(RUN_ID, state).refusal is None

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
        state = State(make_ticket(title=title), [make_ticket(8)])

        assert check(RUN_ID, state).branch == branch


class TestOutputs:
    @pytest.mark.parametrize(
        ("result", "expected"),
        [
            pytest.param(
                CheckResult(url=f"{URL}/7"),
                {"url": f"{URL}/7"},
                id="sets only the URL when every other field is false or unset",
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
                    last_run=True,
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
                    "last-run": "true",
                },
                id="sets each field as the output named after it in kebab case",
            ),
        ],
    )
    def test_returns_the_check_job_s_step_outputs(
        self, result: CheckResult, expected: dict[str, str]
    ) -> None:
        assert outputs(result) == expected


class TestBlockedChildTickets:
    @pytest.mark.parametrize(
        ("children", "blocked"),
        [
            pytest.param(
                [make_ticket(8, blocked_by=1), make_ticket(9)],
                [],
                id="reads no blockers while an open child ticket is unblocked",
            ),
            pytest.param(
                [
                    make_ticket(8, blocked_by=1),
                    make_ticket(9, is_open=False),
                    make_ticket(10, blocked_by=2),
                ],
                [8, 10],
                id="reads the blockers of every open child ticket when none is "
                "unblocked",
            ),
            pytest.param([], [], id="reads no blockers of a ticket without children"),
        ],
    )
    def test_returns_the_child_tickets_whose_blockers_decide_the_run(
        self, children: list[Ticket], blocked: list[int]
    ) -> None:
        assert blocked_child_tickets(children) == blocked


class TestTicket:
    @pytest.mark.parametrize(
        ("issue", "expected"),
        [
            pytest.param(
                make_issue(8, blocked_by=2),
                make_ticket(8, blocked_by=2),
                id="reads an open ticket without a parent",
            ),
            pytest.param(
                {
                    **make_issue(9, state="closed"),
                    "parent_issue_url": "https://api.github.com/repos/owner/repo/issues/3",
                },
                make_ticket(9, is_open=False, parent=3),
                id="reads a closed ticket's parent from its URL",
            ),
        ],
    )
    def test_reads_the_ticket_from_the_issues_api(
        self, issue: dict[str, Any], expected: Ticket
    ) -> None:
        assert ticket(issue) == expected


class TestOpenBlockerUrls:
    def test_reads_the_urls_of_the_open_blocking_tickets(self) -> None:
        response = [
            {"html_url": f"{URL}/9", "state": "open"},
            {"html_url": f"{URL}/4", "state": "closed"},
        ]

        assert open_blocker_urls(response) == (f"{URL}/9",)


def make_closing_response(*nodes: tuple[int, str]) -> dict[str, Any]:
    references = {"nodes": [{"url": f"{PR_URL}/{n}", "state": s} for n, s in nodes]}
    return {
        "data": {
            "repository": {"issue": {"closedByPullRequestsReferences": references}}
        }
    }


class TestOpenClosingPullRequests:
    def test_reads_the_urls_of_the_open_closing_pull_requests(self) -> None:
        response = make_closing_response((20, "MERGED"), (21, "OPEN"), (22, "CLOSED"))

        assert open_closing_pull_requests(response) == (f"{PR_URL}/21",)


ENV = {
    "AFK_APP_TOKEN": "app-token",
    "AFK_WORKFLOW_TOKEN": "workflow-token",
    "AFK_TICKET": "7",
    "GITHUB_RUN_ID": RUN_ID,
    "GH_REPO": "owner/repo",
}
ISSUE_READ = ("gh", "api", "repos/owner/repo/issues/7")
CHILD_TICKETS_READ = ("gh", "api", "repos/owner/repo/issues/7/sub_issues?per_page=100")
CLOSING_PULL_REQUESTS_READ = ("gh", "api", "graphql")
PLAIN_TICKET_READS: dict[tuple[str, ...], str] = {
    ISSUE_READ: json.dumps(make_issue(7)),
    CHILD_TICKETS_READ: "[]",
    CLOSING_PULL_REQUESTS_READ: json.dumps(make_closing_response()),
}


class TestRun:
    def test_marks_the_ticket_in_progress_before_its_reads(
        self, tmp_path: Path
    ) -> None:
        gh = GhSpy(PLAIN_TICKET_READS)

        run_check.run(gh, ENV, Writer(gh, ENV, tmp_path / "output"))

        assert gh.calls[0] == GhCall(
            ["gh", "issue", "edit", "7", "--add-label", "afk:in-progress"],
            "app-token",
            "owner/repo",
        )

    def test_reads_with_the_workflow_token(self, tmp_path: Path) -> None:
        gh = GhSpy(PLAIN_TICKET_READS)

        run_check.run(gh, ENV, Writer(gh, ENV, tmp_path / "output"))

        assert {call.token for call in gh.calls[1:]} == {"workflow-token"}

    def test_refuses_a_ticket_that_an_open_pr_closes(self, tmp_path: Path) -> None:
        gh = GhSpy(
            {
                **PLAIN_TICKET_READS,
                CLOSING_PULL_REQUESTS_READ: json.dumps(
                    make_closing_response((20, "OPEN"))
                ),
            }
        )
        output = tmp_path / "output"

        run_check.run(gh, ENV, Writer(gh, ENV, output))

        closing_read = next(c for c in gh.calls if "graphql" in c.args)
        assert closing_read.args[-6:] == [
            "-f",
            "owner=owner",
            "-f",
            "repo=repo",
            "-F",
            "number=7",
        ]
        assert read_outputs(output)["refusal"] == make_pr_refusal(20)

    def test_sets_the_decision_and_the_planned_mark_as_outputs(
        self, tmp_path: Path
    ) -> None:
        gh = GhSpy(PLAIN_TICKET_READS)
        env = {**ENV, "AFK_DRY_RUN": "true"}
        output = tmp_path / "output"
        writer = Writer(gh, env, output)

        run_check.run(gh, env, writer)
        writer.report()

        assert read_outputs(output) == {
            "url": f"{URL}/7",
            "branch": "afk/issue-7-4242",
            "last-run": "true",
            "effects": json.dumps(
                [
                    {
                        "type": "EditLabels",
                        "number": 7,
                        "add": ["afk:in-progress"],
                        "remove": [],
                    }
                ]
            ),
        }

    def test_reads_the_blockers_of_a_spec_s_blocked_child_tickets(
        self, tmp_path: Path
    ) -> None:
        children = [make_issue(8, blocked_by=1)]
        blockers_read = (
            "gh",
            "api",
            "repos/owner/repo/issues/8/dependencies/blocked_by?per_page=100",
        )
        gh = GhSpy(
            {
                **PLAIN_TICKET_READS,
                CHILD_TICKETS_READ: json.dumps(children),
                blockers_read: json.dumps([{"html_url": f"{URL}/50", "state": "open"}]),
            }
        )
        output = tmp_path / "output"

        run_check.run(gh, ENV, Writer(gh, ENV, output))

        assert read_outputs(output) == {"url": f"{URL}/7", "queue": "true"}
