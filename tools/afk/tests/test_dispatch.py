"""Guards how an AFK command is refused, queued or dispatched, and released."""

import json
import subprocess
from collections.abc import Mapping, Sequence

import pytest

from afk import dispatch
from afk.dispatch import (
    Accept,
    Kind,
    Queue,
    Refusal,
    State,
    Target,
    Verb,
    decide,
    open_blockers,
    parse,
    plan,
    release,
)
from afk.effects import Comment, DispatchWorkflow, React, RemoveLabel, ReplaceLabel


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
                State(
                    labels=frozenset({"afk:in-progress", "afk:queued"}),
                    open_blockers=(4,),
                ),
                Refusal(
                    "Refused: an AFK run is already queued or running here "
                    "(`afk:in-progress`)."
                ),
                id="refuses a target in progress before anything else",
            ),
            pytest.param(
                Verb.UPDATE_BRANCH,
                Kind.PR,
                State(labels=frozenset({"afk:queued"}), head_sha=HEAD_SHA),
                Refusal(
                    "Refused: this ticket is waiting (`afk:queued`) and starts when "
                    "it is unblocked."
                ),
                id="refuses a queued target",
            ),
            pytest.param(
                Verb.IMPLEMENT,
                Kind.ISSUE,
                State(labels=frozenset({"afk:blocked"}), open_blockers=(4, 9)),
                Queue(blockers=(4, 9)),
                id="queues a ticket with open blockers",
            ),
            pytest.param(
                Verb.IMPLEMENT,
                Kind.ISSUE,
                State(labels=frozenset({"ready-for-agent"})),
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
        self, verb: Verb, kind: Kind, state: State, decision: Refusal | Queue | Accept
    ) -> None:
        assert decide(verb, kind, state) == decision


TARGET = Target(number=7, comment_id=555)


class TestPlan:
    def test_plans_a_refusal_as_a_reply_and_a_confused_reaction(self) -> None:
        effects = plan(TARGET, Refusal("Refused."))

        assert effects == [
            Comment(number=7, body="Refused."),
            React(comment_id=555, content="confused"),
        ]

    def test_plans_a_queue_with_a_reply_that_carries_the_command(self) -> None:
        effects = plan(TARGET, Queue(blockers=(4, 9)))

        assert effects == [
            React(comment_id=555, content="eyes"),
            ReplaceLabel(number=7, remove="afk:blocked", add="afk:queued"),
            Comment(
                number=7,
                body="Queued (`afk:queued`) until its blocking tickets close: #4, #9. "
                "The AFK run starts when the last one closes. "
                "<!-- afk-command: 555 -->",
            ),
        ]

    def test_plans_an_acceptance_as_in_progress_before_the_dispatch(self) -> None:
        effects = plan(TARGET, Accept(workflow="afk-run.yml", head_sha=None))

        assert effects == [
            React(comment_id=555, content="eyes"),
            ReplaceLabel(number=7, remove="afk:blocked", add="afk:in-progress"),
            DispatchWorkflow(
                workflow="afk-run.yml", inputs={"number": "7", "comment-id": "555"}
            ),
        ]

    def test_plans_a_dispatch_at_the_head_it_read(self) -> None:
        effects = plan(TARGET, Accept(workflow="afk-run-pr.yml", head_sha=HEAD_SHA))

        assert effects[-1] == DispatchWorkflow(
            workflow="afk-run-pr.yml",
            inputs={"number": "7", "comment-id": "555", "head-sha": HEAD_SHA},
        )


class TestRelease:
    def test_releases_an_accepted_target_and_reacts_confused(self) -> None:
        assert release(TARGET, accepted=True) == [
            RemoveLabel(number=7, label="afk:in-progress"),
            React(comment_id=555, content="confused"),
        ]

    def test_leaves_the_labels_of_a_target_it_did_not_accept(self) -> None:
        assert release(TARGET, accepted=False) == [
            React(comment_id=555, content="confused")
        ]


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
    "AFK_KIND": "issue",
    "AFK_COMMENT_ID": "555",
    "GH_REPO": "owner/repo",
}


class OutputSpy:
    def __init__(self) -> None:
        self.outputs: list[dict[str, str]] = []

    def __call__(self, outputs: Mapping[str, str]) -> None:
        self.outputs.append(dict(outputs))


def gh_dummy(args: Sequence[str], _env: Mapping[str, str]) -> str:
    pytest.fail(f"ran {list(args)}")


class GhFake:
    """Answers the reads of an unlabelled, unblocked issue and fails the dispatch."""

    def __init__(self) -> None:
        self.writes: list[list[str]] = []

    def __call__(self, args: Sequence[str], _env: Mapping[str, str]) -> str:
        match list(args):
            case ["gh", "api", "repos/owner/repo/issues/7"]:
                return json.dumps({"labels": []})
            case ["gh", "api", "graphql", *_]:
                nodes: list[object] = []
                issue = {"blockedBy": {"nodes": nodes}}
                return json.dumps({"data": {"repository": {"issue": issue}}})
            case ["gh", "workflow", "run", *_]:
                raise subprocess.CalledProcessError(1, args)
            case write:
                self.writes.append(write)
                return ""


class TestRun:
    @pytest.mark.parametrize(
        ("body", "effects"),
        [
            pytest.param("Looks good.", [], id="writes nothing for a non-command"),
            pytest.param(
                "/afk deploy",
                [
                    {
                        "type": "Comment",
                        "number": 7,
                        "body": "Unknown AFK command. The first line of the comment "
                        "must be `/afk implement` or `/afk update-branch`.",
                    },
                    {"type": "React", "comment_id": 555, "content": "confused"},
                ],
                id="refuses an unknown verb",
            ),
        ],
    )
    def test_reads_nothing_without_a_known_verb(
        self, body: str, effects: list[dict[str, object]]
    ) -> None:
        output = OutputSpy()

        dispatch.run(gh_dummy, {**ENV, "AFK_BODY": body, "AFK_DRY_RUN": "true"}, output)

        assert [json.loads(o["effects"]) for o in output.outputs] == [effects]

    def test_sets_accepted_before_a_dispatch_that_fails(self) -> None:
        gh = GhFake()
        output = OutputSpy()

        with pytest.raises(subprocess.CalledProcessError):
            dispatch.run(gh, {**ENV, "AFK_BODY": "/afk implement"}, output)

        assert output.outputs == [{"accepted": "true"}]
        assert gh.writes == [
            [
                "gh",
                "api",
                "--method",
                "POST",
                "repos/{owner}/{repo}/issues/comments/555/reactions",
                "-f",
                "content=eyes",
            ],
            [
                "gh",
                "issue",
                "edit",
                "7",
                "--remove-label",
                "afk:blocked",
                "--add-label",
                "afk:in-progress",
            ],
        ]


class TestRunRelease:
    @pytest.mark.parametrize(
        ("accepted", "effects"),
        [
            pytest.param(
                "true",
                [
                    {"type": "RemoveLabel", "number": 7, "label": "afk:in-progress"},
                    {"type": "React", "comment_id": 555, "content": "confused"},
                ],
                id="releases an accepted target",
            ),
            pytest.param(
                "",
                [{"type": "React", "comment_id": 555, "content": "confused"}],
                id="only reacts when the command was not accepted",
            ),
        ],
    )
    def test_reads_accepted_from_the_dispatch_output(
        self, accepted: str, effects: list[dict[str, object]]
    ) -> None:
        output = OutputSpy()
        env = {**ENV, "AFK_ACCEPTED": accepted, "AFK_DRY_RUN": "true"}

        dispatch.run_release(gh_dummy, env, output)

        assert [json.loads(o["effects"]) for o in output.outputs] == [effects]
