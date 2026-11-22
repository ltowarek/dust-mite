"""Guards what an AFK PR run pushes and posts from the agent's structured output."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from afk import run_pr_publish
from afk.effects import (
    Comment,
    CreateReviewComment,
    EditLabels,
    Effect,
    PushBranch,
    ReplyToReviewComment,
)
from afk.github import PullRequest
from afk.run_pr_publish import acted, plan
from afk.writer import Writer
from tests.test_doubles import GhSpy, GitCall, GitSpy, read_outputs

PR = PullRequest(number=9, branch="feature", head_sha="head123")
PUSH = PushBranch(repository="owner/repo", branch="feature", lease="head123")


def make_output(**fields: object) -> dict[str, Any]:
    return {
        "thread_replies": [],
        "inline_comments": [],
        "top_level_comments": [],
        "needs_dut_run": False,
        **fields,
    }


class TestPlan:
    @pytest.mark.parametrize(
        ("output", "commits", "effects"),
        [
            pytest.param(
                make_output(),
                2,
                [PUSH],
                id="pushes the agent's commits with a lease on the PR's head",
            ),
            pytest.param(
                make_output(top_level_comments=["Nothing to change."]),
                0,
                [Comment(number=9, body="Nothing to change.")],
                id="pushes nothing without commits",
            ),
            pytest.param(
                make_output(
                    thread_replies=[{"comment_id": 501, "body": "Done."}],
                    inline_comments=[{"path": "docs/a.md", "line": 4, "body": "Note."}],
                    top_level_comments=["Summary."],
                ),
                1,
                [
                    PUSH,
                    ReplyToReviewComment(number=9, comment_id=501, body="Done."),
                    CreateReviewComment(
                        number=9,
                        commit="abc123",
                        path="docs/a.md",
                        line=4,
                        body="Note.",
                    ),
                    Comment(number=9, body="Summary."),
                ],
                id="posts the replies then the inline then the top-level comments",
            ),
            pytest.param(
                make_output(needs_dut_run=True, car_variant="copper"),
                1,
                [PUSH, EditLabels(number=9, add=("needs-car:copper",))],
                id="labels the PR for the car when its commits need a DUT run",
            ),
            pytest.param(
                make_output(
                    needs_dut_run=True,
                    car_variant="copper",
                    top_level_comments=["Needs the car."],
                ),
                0,
                [Comment(number=9, body="Needs the car.")],
                id="leaves the car label when there are no commits to run",
            ),
        ],
    )
    def test_plans_the_pushes_comments_and_label(
        self, output: dict[str, Any], commits: int, effects: list[Effect]
    ) -> None:
        assert (
            plan(output, PR, repository="owner/repo", commits=commits, head="abc123")
            == effects
        )


class TestActed:
    @pytest.mark.parametrize(
        ("output", "commits", "expected"),
        [
            pytest.param(make_output(), 1, True, id="acted when it committed"),
            pytest.param(
                make_output(thread_replies=[{"comment_id": 501, "body": "No."}]),
                0,
                True,
                id="acted when it only replied",
            ),
            pytest.param(
                make_output(inline_comments=[{"path": "a", "line": 1, "body": "x"}]),
                0,
                True,
                id="acted when it only commented inline",
            ),
            pytest.param(
                make_output(top_level_comments=["Done."]),
                0,
                True,
                id="acted when it only commented on the PR",
            ),
            pytest.param(
                make_output(), 0, False, id="did not act without commits or comments"
            ),
        ],
    )
    def test_tells_whether_the_agent_committed_or_commented(
        self, output: dict[str, Any], commits: int, *, expected: bool
    ) -> None:
        assert acted(output, commits) is expected


ENV = {
    "AFK_AGENT_OUTCOME": "success",
    "AFK_AGENT_OUTPUT": json.dumps(
        make_output(
            inline_comments=[
                {"path": "docs/a.md", "line": 4, "body": "Note."},
                {"path": "docs/b.md", "line": 2, "body": "Other."},
            ],
            top_level_comments=["Summary."],
        )
    ),
    "AFK_APP_TOKEN": "app-token",
    "AFK_BRANCH": "feature",
    "AFK_HEAD_SHA": "head123",
    "AFK_PR": "9",
    "GH_REPO": "owner/repo",
}
CHANGED_FILES_READ = (
    "--no-replace-objects",
    "log",
    "-z",
    "--format=",
    "--name-only",
    "--no-renames",
    "--diff-merges=first-parent",
    "head123..HEAD",
)
GIT_READS: dict[tuple[str, ...], str] = {
    CHANGED_FILES_READ: "docs/a.md\0",
    ("rev-list", "--count", "head123..HEAD"): "1\n",
    ("rev-parse", "HEAD"): "abc123\n",
}


class TestRun:
    def test_refuses_commits_that_change_github_or_tools_and_writes_nothing(
        self, tmp_path: Path
    ) -> None:
        gh = GhSpy()
        git = GitSpy({**GIT_READS, CHANGED_FILES_READ: "tools/afk/x.py\0"})

        with pytest.raises(SystemExit, match=r"tools/afk/x\.py"):
            run_pr_publish.run(git, ENV, Writer(gh, git, ENV, tmp_path / "out"))

        assert (gh.calls, git.calls) == ([], [GitCall(list(CHANGED_FILES_READ), {})])

    def test_fails_when_the_agent_neither_committed_nor_commented(
        self, tmp_path: Path
    ) -> None:
        env = {**ENV, "AFK_AGENT_OUTPUT": json.dumps(make_output())}
        gh = GhSpy()
        git = GitSpy({**GIT_READS, ("rev-list", "--count", "head123..HEAD"): "0\n"})

        with pytest.raises(SystemExit, match="neither committed nor commented"):
            run_pr_publish.run(git, env, Writer(gh, git, env, tmp_path / "out"))

        assert gh.calls == []

    def test_reports_the_planned_writes_in_a_dry_run(self, tmp_path: Path) -> None:
        env = {**ENV, "AFK_DRY_RUN": "true"}
        gh, git = GhSpy(), GitSpy(GIT_READS)
        output = tmp_path / "out"
        writer = Writer(gh, git, env, output)

        run_pr_publish.run(git, env, writer)
        writer.report()

        assert json.loads(read_outputs(output)["effects"]) == [
            {
                "type": "PushBranch",
                "repository": "owner/repo",
                "branch": "feature",
                "lease": "head123",
            },
            {
                "type": "CreateReviewComment",
                "number": 9,
                "commit": "abc123",
                "path": "docs/a.md",
                "line": 4,
                "body": "Note.",
            },
            {
                "type": "CreateReviewComment",
                "number": 9,
                "commit": "abc123",
                "path": "docs/b.md",
                "line": 2,
                "body": "Other.",
            },
            {"type": "Comment", "number": 9, "body": "Summary."},
        ]

    def test_stops_at_the_first_write_that_fails(self, tmp_path: Path) -> None:
        inline = ("api", "--method", "POST", "repos/{owner}/{repo}/pulls/9/comments")
        gh, git = GhSpy(failing=inline), GitSpy(GIT_READS)

        with pytest.raises(subprocess.CalledProcessError):
            run_pr_publish.run(git, ENV, Writer(gh, git, ENV, tmp_path / "out"))

        assert gh.calls[-1].args[:4] == list(inline)

    def test_after_a_failed_agent_sets_only_its_error(self, tmp_path: Path) -> None:
        execution = tmp_path / "execution.json"
        execution.write_text(
            json.dumps([{"type": "result", "is_error": True, "result": "Stuck."}])
        )
        env = {
            **ENV,
            "AFK_AGENT_OUTCOME": "failure",
            "AFK_AGENT_OUTPUT": "",
            "AFK_EXECUTION_FILE": str(execution),
        }
        gh, git = GhSpy(), GitSpy()
        output = tmp_path / "out"

        run_pr_publish.run(git, env, Writer(gh, git, env, output))

        assert (read_outputs(output), gh.calls, git.calls) == (
            {"agent-error": "Stuck."},
            [],
            [],
        )
