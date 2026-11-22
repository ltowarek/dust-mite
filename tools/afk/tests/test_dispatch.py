"""Guards how an AFK command is refused, queued or dispatched, and released."""

import json
import subprocess
from pathlib import Path

import pytest

from afk import dispatch
from afk.dispatch import (
    Accept,
    Issue,
    Kind,
    Queue,
    Refusal,
    State,
    Target,
    Verb,
    decide,
    issue,
    open_blockers,
    parse,
    plan,
    refusal,
    release,
)
from afk.effects import Comment, DispatchWorkflow, EditLabels, Effect, React
from afk.writer import Writer
from tests.test_doubles import GhSpy, read_outputs


class TestParse:
    @pytest.mark.parametrize(
        ("body", "verb"),
        [
            pytest.param("/afk implement", Verb.IMPLEMENT, id="reads implement"),
            pytest.param(
                "/afk update-branch", Verb.UPDATE_BRANCH, id="reads update-branch"
            ),
            pytest.param(
                "/afk implement \t\r\nPlease hurry.",
                Verb.IMPLEMENT,
                id="reads only the first line without its trailing whitespace",
            ),
            pytest.param("/afk", Verb.UNKNOWN, id="reads a bare /afk as unknown"),
            pytest.param(
                "/afk deploy", Verb.UNKNOWN, id="reads another verb as unknown"
            ),
            pytest.param(
                " /afk implement", None, id="ignores a command after leading space"
            ),
            pytest.param("/afkimplement", None, id="ignores /afk without a space"),
            pytest.param(
                "Thanks!\n/afk implement", None, id="ignores a command on a later line"
            ),
        ],
    )
    def test_reads_the_command_from_the_first_line(
        self, body: str, verb: Verb | None
    ) -> None:
        assert parse(body) == verb


HEAD_SHA = "a409d695e7b5cf239464dc91706ee9585251231f"


class TestDecide:
    @pytest.mark.parametrize(
        ("verb", "kind", "state", "decision"),
        [
            pytest.param(
                Verb.IMPLEMENT,
                Kind.ISSUE,
                State(open_blockers=(4, 9)),
                Queue(blockers=(4, 9)),
                id="queues a ticket with open blockers",
            ),
            pytest.param(
                Verb.IMPLEMENT,
                Kind.ISSUE,
                State(),
                Accept(workflow="afk-run.yml", head_sha=None),
                id="runs an issue's implementation",
            ),
            pytest.param(
                Verb.IMPLEMENT,
                Kind.PR,
                State(head_sha=HEAD_SHA),
                Accept(workflow="afk-run-pr.yml", head_sha=HEAD_SHA),
                id="runs a PR's implementation at its head",
            ),
            pytest.param(
                Verb.UPDATE_BRANCH,
                Kind.PR,
                State(head_sha=HEAD_SHA),
                Accept(workflow="afk-update-branch.yml", head_sha=HEAD_SHA),
                id="updates a PR's branch at its head",
            ),
            pytest.param(
                Verb.UPDATE_BRANCH,
                Kind.ISSUE,
                State(),
                Accept(workflow="afk-update-branch.yml", head_sha=None),
                id="updates an issue's branch",
            ),
        ],
    )
    def test_decides_what_a_command_does(
        self, verb: Verb, kind: Kind, state: State, decision: Queue | Accept
    ) -> None:
        assert decide(verb, kind, state) == decision


class TestRefusal:
    @pytest.mark.parametrize(
        ("labels", "decision"),
        [
            pytest.param(
                {"afk:in-progress", "afk:queued"},
                Refusal(
                    "Refused: an AFK run is already queued or running here "
                    "(`afk:in-progress`)."
                ),
                id="refuses a target in progress before a queued one",
            ),
            pytest.param(
                {"afk:queued"},
                Refusal(
                    "Refused: this ticket is waiting (`afk:queued`) and starts when "
                    "it is unblocked."
                ),
                id="refuses a queued target",
            ),
            pytest.param(
                {"afk:blocked", "ready-for-agent"}, None, id="refuses no other target"
            ),
        ],
    )
    def test_refuses_a_target_by_its_labels(
        self, labels: set[str], decision: Refusal | None
    ) -> None:
        assert refusal(frozenset(labels)) == decision


TARGET = Target(number=7, comment_id=555)


class TestPlan:
    @pytest.mark.parametrize(
        ("decision", "effects"),
        [
            pytest.param(
                Refusal("Refused."),
                [
                    Comment(number=7, body="Refused."),
                    React(comment_id=555, content="confused"),
                ],
                id="plans a refusal as a reply and a confused reaction",
            ),
            pytest.param(
                Queue(blockers=(4, 9)),
                [
                    React(comment_id=555, content="eyes"),
                    EditLabels(number=7, add=("afk:queued",), remove=("afk:blocked",)),
                    Comment(
                        number=7,
                        body="Queued (`afk:queued`) until its blocking tickets close: "
                        "#4, #9. The AFK run starts when the last one closes. "
                        "<!-- afk-command: 555 -->",
                    ),
                ],
                id="plans a queue with a reply that carries the command",
            ),
            pytest.param(
                Accept(workflow="afk-run.yml", head_sha=None),
                [
                    React(comment_id=555, content="eyes"),
                    EditLabels(
                        number=7, add=("afk:in-progress",), remove=("afk:blocked",)
                    ),
                    DispatchWorkflow(
                        workflow="afk-run.yml",
                        inputs={"number": "7", "comment-id": "555"},
                    ),
                ],
                id="plans an acceptance as in progress before the dispatch",
            ),
            pytest.param(
                Accept(workflow="afk-run-pr.yml", head_sha=HEAD_SHA),
                [
                    React(comment_id=555, content="eyes"),
                    EditLabels(
                        number=7, add=("afk:in-progress",), remove=("afk:blocked",)
                    ),
                    DispatchWorkflow(
                        workflow="afk-run-pr.yml",
                        inputs={
                            "number": "7",
                            "comment-id": "555",
                            "head-sha": HEAD_SHA,
                        },
                    ),
                ],
                id="plans a dispatch at the head it read",
            ),
        ],
    )
    def test_plans_the_writes_of_a_decision(
        self, decision: Refusal | Queue | Accept, effects: list[Effect]
    ) -> None:
        assert plan(TARGET, decision) == effects


class TestRelease:
    @pytest.mark.parametrize(
        ("accepted", "effects"),
        [
            pytest.param(
                True,
                [
                    EditLabels(number=7, remove=("afk:in-progress",)),
                    React(comment_id=555, content="confused"),
                ],
                id="releases an accepted target and reacts confused",
            ),
            pytest.param(
                False,
                [React(comment_id=555, content="confused")],
                id="leaves the labels of a target it did not accept",
            ),
        ],
    )
    def test_plans_the_writes_of_a_release(
        self, *, accepted: bool, effects: list[Effect]
    ) -> None:
        assert release(TARGET, accepted=accepted) == effects


class TestIssue:
    @pytest.mark.parametrize(
        ("response", "expected"),
        [
            pytest.param(
                {"labels": [{"name": "afk:blocked"}, {"name": "bug"}]},
                Issue(kind=Kind.ISSUE, labels=frozenset({"afk:blocked", "bug"})),
                id="reads an issue and its labels",
            ),
            pytest.param(
                {
                    "labels": [],
                    "pull_request": {"url": "https://api.github.com/repos/o/r/pulls/7"},
                },
                Issue(kind=Kind.PR, labels=frozenset()),
                id="reads a pull request from its pull_request key",
            ),
        ],
    )
    def test_reads_the_kind_and_labels(
        self, response: dict[str, object], expected: Issue
    ) -> None:
        assert issue(response) == expected


class TestOpenBlockers:
    def test_keeps_the_open_blocking_tickets_in_order(self) -> None:
        nodes = [
            {"number": 9, "state": "OPEN"},
            {"number": 5, "state": "CLOSED"},
            {"number": 4, "state": "OPEN"},
        ]
        response = {"data": {"repository": {"issue": {"blockedBy": {"nodes": nodes}}}}}

        assert open_blockers(response) == (9, 4)


ENV = {
    "AFK_APP_TOKEN": "app-token",
    "AFK_WORKFLOW_TOKEN": "workflow-token",
    "AFK_NUMBER": "7",
    "AFK_COMMENT_ID": "555",
    "AFK_BODY": "/afk implement",
    "GH_REPO": "owner/repo",
}
ISSUE_READ = ("gh", "api", "repos/owner/repo/issues/7")
NO_BLOCKERS = json.dumps(
    {"data": {"repository": {"issue": {"blockedBy": {"nodes": []}}}}}
)


class TestRun:
    def test_reads_only_the_labels_of_a_refused_target(self, tmp_path: Path) -> None:
        gh = GhSpy({ISSUE_READ: json.dumps({"labels": [{"name": "afk:in-progress"}]})})
        env = {**ENV, "AFK_DRY_RUN": "true"}

        dispatch.run(gh, env, Writer(gh, env, tmp_path / "output"))

        assert [call.args for call in gh.calls] == [list(ISSUE_READ)]

    def test_sets_accepted_before_a_dispatch_that_fails(self, tmp_path: Path) -> None:
        gh = GhSpy(
            {
                ISSUE_READ: json.dumps({"labels": []}),
                ("gh", "api", "graphql"): NO_BLOCKERS,
            },
            failing=("gh", "workflow", "run"),
        )
        output = tmp_path / "output"

        with pytest.raises(subprocess.CalledProcessError):
            dispatch.run(gh, ENV, Writer(gh, ENV, output))

        assert read_outputs(output) == {"accepted": "true"}
