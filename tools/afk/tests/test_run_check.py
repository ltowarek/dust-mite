"""Guards whether an AFK run refuses, queues or proceeds, and on which branch."""

import json
from pathlib import Path

import pytest

from afk import run_check
from afk.run_check import (
    CheckResult,
    ChildTicket,
    PullRequest,
    State,
    Ticket,
    blocked_child_tickets,
    check,
    child_tickets,
    open_blocker_urls,
    pull_requests,
    ticket,
)
from afk.writer import Writer
from tests.test_doubles import GhCall, GhSpy, read_outputs

RUN_ID = "4242"
URL = "https://github.com/owner/repo/issues"


def make_ticket(
    title: str = "Fix the thing",
    parent: int | None = None,
    open_blocking_tickets: int = 0,
) -> Ticket:
    return Ticket(
        url=f"{URL}/7",
        title=title,
        parent=parent,
        open_blocking_tickets=open_blocking_tickets,
    )


def make_child(
    number: int, *, is_open: bool = True, blocked_by: int = 0
) -> ChildTicket:
    return ChildTicket(
        number=number,
        url=f"{URL}/{number}",
        open=is_open,
        open_blocking_tickets=blocked_by,
    )


def make_pull_request(number: int, body: str) -> PullRequest:
    return PullRequest(url=f"https://github.com/owner/repo/pull/{number}", body=body)


def make_pr_refusal(number: int) -> str:
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
        ("state", "result"),
        [
            pytest.param(
                State(make_ticket()),
                CheckResult(url=f"{URL}/7", branch="afk/issue-7-4242", last_run=True),
                id="runs a plain ticket on its own branch in one run",
            ),
            pytest.param(
                State(make_ticket(open_blocking_tickets=1)),
                CheckResult(
                    url=f"{URL}/7",
                    refusal="Refused to run: this ticket has an open blocking "
                    "ticket. Comment `/afk implement` to queue it until its last "
                    "blocking ticket closes.",
                ),
                id="refuses a ticket with an open blocking ticket",
            ),
            pytest.param(
                State(make_ticket(parent=3, open_blocking_tickets=1)),
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
                    [make_child(8, is_open=False), make_child(9, is_open=False)],
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
                        make_child(8, is_open=False),
                        make_child(9, blocked_by=1),
                        make_child(10),
                        make_child(11),
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
                    [make_child(8, is_open=False), make_child(9)],
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
                    [make_child(8, blocked_by=1), make_child(9, blocked_by=1)],
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
                    [make_child(8, blocked_by=1), make_child(9, blocked_by=1)],
                    open_blocker_urls={8: [f"{URL}/9"], 9: [f"{URL}/50"]},
                ),
                CheckResult(url=f"{URL}/7", queue=True),
                id="queues a spec whose open child tickets wait on another ticket",
            ),
            pytest.param(
                State(
                    make_ticket(),
                    pull_requests=[
                        make_pull_request(20, "#7"),
                        make_pull_request(21, "Closes #7"),
                    ],
                ),
                CheckResult(
                    url=f"{URL}/7",
                    refusal=make_pr_refusal(21),
                    branch="afk/issue-7-4242",
                    last_run=True,
                ),
                id="refuses a ticket that the first open PR to close it names",
            ),
            pytest.param(
                State(
                    make_ticket(),
                    [make_child(8, blocked_by=1)],
                    open_blocker_urls={8: [f"{URL}/50"]},
                    pull_requests=[make_pull_request(20, "Closes #7")],
                ),
                CheckResult(url=f"{URL}/7", refusal=make_pr_refusal(20), queue=True),
                id="queues and refuses a spec that an open PR closes",
            ),
        ],
    )
    def test_decides_whether_the_run_goes_ahead(
        self, state: State, result: CheckResult
    ) -> None:
        assert check(7, RUN_ID, state) == result

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param("Closes #7", id="closes"),
            pytest.param("Some text.\n\nfixes\n#7.", id="fixes on the next line"),
            pytest.param("RESOLVES #7", id="resolves in capitals"),
        ],
    )
    def test_refuses_a_ticket_that_an_open_pr_closes(self, body: str) -> None:
        state = State(make_ticket(), pull_requests=[make_pull_request(20, body)])

        assert check(7, RUN_ID, state).refusal == make_pr_refusal(20)

    @pytest.mark.parametrize(
        "state",
        [
            pytest.param(
                State(make_ticket(), pull_requests=[make_pull_request(20, "Refs #7")]),
                id="refers to the ticket",
            ),
            pytest.param(
                State(
                    make_ticket(), pull_requests=[make_pull_request(20, "Closes #70")]
                ),
                id="closes a longer number",
            ),
            pytest.param(
                State(make_ticket(), pull_requests=[make_pull_request(20, "Closes#7")]),
                id="has no space before the number",
            ),
            pytest.param(
                State(
                    make_ticket(),
                    [make_child(8)],
                    pull_requests=[make_pull_request(20, "Closes #7")],
                ),
                id="closes the spec whose child ticket runs",
            ),
        ],
    )
    def test_runs_a_ticket_despite_an_open_pr_that(self, state: State) -> None:
        assert check(7, RUN_ID, state).refusal is None

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
        state = State(make_ticket(title=title), [make_child(8)])

        assert check(7, RUN_ID, state).branch == branch


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


class TestBlockedChildTickets:
    @pytest.mark.parametrize(
        ("children", "blocked"),
        [
            pytest.param(
                [make_child(8, blocked_by=1), make_child(9)],
                [],
                id="reads no blockers while an open child ticket is unblocked",
            ),
            pytest.param(
                [
                    make_child(8, blocked_by=1),
                    make_child(9, is_open=False),
                    make_child(10, blocked_by=2),
                ],
                [8, 10],
                id="reads the blockers of every open child ticket when none is "
                "unblocked",
            ),
            pytest.param([], [], id="reads no blockers of a ticket without children"),
        ],
    )
    def test_returns_the_child_tickets_whose_blockers_decide_the_run(
        self, children: list[ChildTicket], blocked: list[int]
    ) -> None:
        assert blocked_child_tickets(children) == blocked


class TestTicket:
    @pytest.mark.parametrize(
        ("parent", "expected"),
        [
            pytest.param({"number": 3}, 3, id="reads the parent's number"),
            pytest.param(None, None, id="reads a ticket without a parent"),
        ],
    )
    def test_reads_the_ticket_from_its_view_and_issue(
        self, parent: dict[str, int] | None, expected: int | None
    ) -> None:
        view = {"title": "Fix the thing", "url": f"{URL}/7", "parent": parent}
        issue = {"issue_dependencies_summary": {"blocked_by": 2}}

        assert ticket(view, issue) == Ticket(
            url=f"{URL}/7",
            title="Fix the thing",
            parent=expected,
            open_blocking_tickets=2,
        )


class TestChildTickets:
    def test_reads_each_child_ticket_in_order(self) -> None:
        response = [
            {
                "number": 9,
                "html_url": f"{URL}/9",
                "state": "closed",
                "issue_dependencies_summary": {"blocked_by": 0},
            },
            {
                "number": 8,
                "html_url": f"{URL}/8",
                "state": "open",
                "issue_dependencies_summary": {"blocked_by": 1},
            },
        ]

        assert child_tickets(response) == [
            ChildTicket(number=9, url=f"{URL}/9", open=False, open_blocking_tickets=0),
            ChildTicket(number=8, url=f"{URL}/8", open=True, open_blocking_tickets=1),
        ]


class TestOpenBlockerUrls:
    def test_reads_the_urls_of_the_open_blocking_tickets(self) -> None:
        response = [
            {"html_url": f"{URL}/9", "state": "open"},
            {"html_url": f"{URL}/4", "state": "closed"},
        ]

        assert open_blocker_urls(response) == (f"{URL}/9",)


class TestPullRequests:
    def test_reads_each_pull_request_s_url_and_body(self) -> None:
        response = [{"url": "https://github.com/owner/repo/pull/20", "body": "#7"}]

        assert pull_requests(response) == [make_pull_request(20, "#7")]


ENV = {
    "AFK_APP_TOKEN": "app-token",
    "AFK_WORKFLOW_TOKEN": "workflow-token",
    "AFK_TICKET": "7",
    "GITHUB_RUN_ID": RUN_ID,
    "GH_REPO": "owner/repo",
}
VIEW_READ = ("gh", "issue", "view", "7")
ISSUE_READ = ("gh", "api", "repos/owner/repo/issues/7")
CHILD_TICKETS_READ = ("gh", "api", "repos/owner/repo/issues/7/sub_issues?per_page=100")
PULL_REQUESTS_READ = ("gh", "pr", "list")
PLAIN_TICKET_READS = {
    VIEW_READ: json.dumps(
        {"title": "Fix the thing", "url": f"{URL}/7", "parent": None}
    ),
    ISSUE_READ: json.dumps({"issue_dependencies_summary": {"blocked_by": 0}}),
    CHILD_TICKETS_READ: "[]",
    PULL_REQUESTS_READ: "[]",
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
        children = [
            {
                "number": 8,
                "html_url": f"{URL}/8",
                "state": "open",
                "issue_dependencies_summary": {"blocked_by": 1},
            }
        ]
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
