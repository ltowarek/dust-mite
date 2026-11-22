"""Guards the AFK PR run's check: its mark, its refusals and the conversation."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from afk import run_pr_check
from afk.github import PullRequest
from afk.run_pr_check import (
    CheckResult,
    Conversation,
    State,
    check,
    conversation,
    outputs,
    pull_request_state,
)
from afk.writer import Writer
from tests.test_doubles import GhSpy, GitSpy, read_outputs

STATE = State(
    pull_request=PullRequest(number=9, branch="feature", head_sha="head123"),
    url="https://github.com/owner/repo/pull/9",
    open=True,
    fork=False,
)
CONVERSATION = Conversation(
    issue_comments=({"author": "alice", "body": "Rename it."},),
)


class TestCheck:
    @pytest.mark.parametrize(
        ("state", "conversation", "refusal"),
        [
            pytest.param(
                replace(STATE, open=False),
                CONVERSATION,
                "Refused to run: this PR is not open.",
                id="refuses a PR that is not open",
            ),
            pytest.param(
                replace(STATE, fork=True),
                CONVERSATION,
                "Refused to run: this PR's branch is in a fork, and an AFK run never "
                "runs a fork's code with the repository's secrets.",
                id="refuses a PR whose branch is in a fork",
            ),
            pytest.param(
                STATE,
                Conversation(),
                "Refused to run: this PR has no unresolved review threads, review "
                "summaries or top-level comments to act on.",
                id="refuses a PR with nothing to act on",
            ),
        ],
    )
    def test_refuses_the_run(
        self, state: State, conversation: Conversation, refusal: str
    ) -> None:
        assert check(state, conversation, head_sha="") == CheckResult(refusal=refusal)

    @pytest.mark.parametrize(
        ("head_sha", "expected"),
        [
            pytest.param("", "head123", id="works on the PR's current head"),
            pytest.param(
                "accepted456",
                "accepted456",
                id="works on the head that the AFK command was accepted at",
            ),
        ],
    )
    def test_goes_ahead_on_the_pr_s_branch(self, head_sha: str, expected: str) -> None:
        assert check(STATE, CONVERSATION, head_sha) == CheckResult(
            url="https://github.com/owner/repo/pull/9",
            branch="feature",
            head_sha=expected,
            conversation=CONVERSATION,
        )


def make_view(**fields: object) -> dict[str, Any]:
    return {
        "number": 9,
        "state": "OPEN",
        "url": "https://github.com/owner/repo/pull/9",
        "isCrossRepository": False,
        "headRefName": "feature",
        "headRefOid": "head123",
        "comments": [],
        "reviews": [],
        **fields,
    }


def make_threads(*threads: dict[str, Any]) -> dict[str, Any]:
    return {
        "data": {
            "repository": {"pullRequest": {"reviewThreads": {"nodes": list(threads)}}}
        }
    }


def make_thread(*, resolved: bool, line: int | None = 4) -> dict[str, Any]:
    return {
        "isResolved": resolved,
        "comments": {
            "nodes": [
                {
                    "databaseId": 501,
                    "path": "docs/a.md",
                    "line": line,
                    "originalLine": 3,
                    "body": "Add a line.",
                    "author": {"login": "alice"},
                },
                {
                    "databaseId": 502,
                    "path": "docs/a.md",
                    "line": line,
                    "originalLine": 3,
                    "body": "Agreed.",
                    "author": None,
                },
            ]
        },
    }


class TestPullRequestState:
    @pytest.mark.parametrize(
        ("view", "expected"),
        [
            pytest.param(
                make_view(), STATE, id="reads an open PR from this repository"
            ),
            pytest.param(
                make_view(state="MERGED", isCrossRepository=True),
                replace(STATE, open=False, fork=True),
                id="reads a merged PR from a fork",
            ),
        ],
    )
    def test_reads_the_pr_from_gh_pr_view(
        self, view: dict[str, Any], expected: State
    ) -> None:
        assert pull_request_state(view) == expected


class TestConversation:
    def test_keeps_the_top_level_comments_except_afk_commands(self) -> None:
        view = make_view(
            comments=[
                {"author": {"login": "alice"}, "body": "Rename it."},
                {"author": {"login": "owner"}, "body": "/afk implement"},
            ]
        )

        assert conversation(view, make_threads()).issue_comments == (
            {"author": "alice", "body": "Rename it."},
        )

    def test_keeps_the_review_summaries_that_have_a_body(self) -> None:
        view = make_view(
            reviews=[
                {"author": {"login": "bob"}, "state": "APPROVED", "body": ""},
                {
                    "author": {"login": "alice"},
                    "state": "CHANGES_REQUESTED",
                    "body": "See inline.",
                },
            ]
        )

        assert conversation(view, make_threads()).review_summaries == (
            {"author": "alice", "state": "CHANGES_REQUESTED", "body": "See inline."},
        )

    @pytest.mark.parametrize(
        ("line", "expected_line"),
        [
            pytest.param(4, 4, id="anchors a thread at its line"),
            pytest.param(None, 3, id="anchors an outdated thread at its original line"),
        ],
    )
    def test_keeps_the_unresolved_threads_for_replies_to_their_first_comment(
        self, line: int | None, expected_line: int
    ) -> None:
        threads = make_threads(
            make_thread(resolved=True), make_thread(resolved=False, line=line)
        )

        assert conversation(make_view(), threads).review_threads == (
            {
                "comment_id": 501,
                "path": "docs/a.md",
                "line": expected_line,
                "comments": [
                    {"author": "alice", "body": "Add a line."},
                    {"author": None, "body": "Agreed."},
                ],
            },
        )


class TestOutputs:
    @pytest.mark.parametrize(
        ("result", "expected"),
        [
            pytest.param(
                CheckResult(refusal="Refused."),
                {"refusal": "Refused."},
                id="sets only the refusal of a refused run",
            ),
            pytest.param(
                CheckResult(
                    url="https://github.com/owner/repo/pull/9",
                    branch="feature",
                    head_sha="head123",
                    conversation=CONVERSATION,
                ),
                {
                    "url": "https://github.com/owner/repo/pull/9",
                    "branch": "feature",
                    "head-sha": "head123",
                    "conversation": '{"issue_comments": [{"author": "alice", '
                    '"body": "Rename it."}], "review_summaries": [], '
                    '"review_threads": []}',
                },
                id="sets the PR and its conversation as JSON for a run that goes ahead",
            ),
        ],
    )
    def test_returns_the_check_job_s_step_outputs(
        self, result: CheckResult, expected: dict[str, str]
    ) -> None:
        assert outputs(result) == expected


ENV = {
    "AFK_PR": "9",
    "AFK_HEAD_SHA": "",
    "AFK_APP_TOKEN": "app-token",
    "AFK_WORKFLOW_TOKEN": "workflow-token",
    "GH_REPO": "owner/repo",
}
GH_READS = {
    (
        "pr",
        "view",
        "9",
        "--json",
        "number,state,url,isCrossRepository,headRefName,headRefOid,comments,reviews",
    ): json.dumps(
        make_view(comments=[{"author": {"login": "alice"}, "body": "Rename it."}])
    ),
    ("api", "graphql"): json.dumps(make_threads()),
}


class TestRun:
    def test_marks_the_pr_in_progress_before_its_reads(self, tmp_path: Path) -> None:
        gh = GhSpy(GH_READS)

        run_pr_check.run(gh, ENV, Writer(gh, GitSpy(), ENV, tmp_path / "output"))

        assert [c.args[:2] for c in gh.calls] == [
            ["issue", "edit"],
            ["pr", "view"],
            ["api", "graphql"],
        ]

    def test_reads_with_the_workflow_token(self, tmp_path: Path) -> None:
        gh = GhSpy(GH_READS)

        run_pr_check.run(gh, ENV, Writer(gh, GitSpy(), ENV, tmp_path / "output"))

        assert {c.token for c in gh.calls[1:]} == {"workflow-token"}

    def test_reads_the_pr_s_threads_by_its_number(self, tmp_path: Path) -> None:
        gh = GhSpy(GH_READS)

        run_pr_check.run(gh, ENV, Writer(gh, GitSpy(), ENV, tmp_path / "output"))

        assert gh.calls[2].args[-6:] == [
            "-f",
            "owner=owner",
            "-f",
            "repo=repo",
            "-F",
            "number=9",
        ]

    def test_sets_the_decision_and_the_planned_mark_as_outputs(
        self, tmp_path: Path
    ) -> None:
        gh = GhSpy(GH_READS)
        env = {**ENV, "AFK_DRY_RUN": "true"}
        output = tmp_path / "output"
        writer = Writer(gh, GitSpy(), env, output)

        run_pr_check.run(gh, env, writer)
        writer.report()

        assert read_outputs(output) == {
            "url": "https://github.com/owner/repo/pull/9",
            "branch": "feature",
            "head-sha": "head123",
            "conversation": '{"issue_comments": [{"author": "alice", "body": '
            '"Rename it."}], "review_summaries": [], "review_threads": []}',
            "effects": '[{"type": "EditLabels", "number": 9, '
            '"add": ["afk:in-progress"], "remove": []}]',
        }
