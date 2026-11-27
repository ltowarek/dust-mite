"""Guards each write's exact command, that a dry run runs none, and the outputs."""

import io
import json
from pathlib import Path

import pytest

from afk.effects import (
    CloseIssue,
    Comment,
    CommentPullRequest,
    CreateIssue,
    CreatePullRequest,
    CreateReviewComment,
    DispatchWorkflow,
    EditLabels,
    EditPullRequest,
    EditPullRequestLabels,
    Effect,
    MarkPullRequestReady,
    PushBranch,
    React,
    ReplyToReviewComment,
    Unreact,
)
from afk.writer import Writer, write_outputs
from tests.test_doubles import GhCall, GhSpy, GitCall, GitSpy, read_outputs

ENV = {
    "AFK_APP_TOKEN": "app-token",
    "AFK_WORKFLOW_TOKEN": "workflow-token",
    "GH_REPO": "owner/repo",
}


class TestWriter:
    class TestWrite:
        @pytest.mark.parametrize(
            ("effect", "args", "token"),
            [
                pytest.param(
                    DispatchWorkflow(
                        workflow="afk-run.yml",
                        inputs={"number": "7", "comment-id": "555"},
                    ),
                    [
                        "workflow",
                        "run",
                        "afk-run.yml",
                        "-f",
                        "number=7",
                        "-f",
                        "comment-id=555",
                    ],
                    "workflow-token",
                    id="dispatches a workflow with the workflow token",
                ),
                pytest.param(
                    EditLabels(
                        number=7,
                        add=("afk:blocked", "bug"),
                        remove=("afk:queued", "afk:in-progress"),
                    ),
                    [
                        "issue",
                        "edit",
                        "7",
                        "--add-label",
                        "afk:blocked",
                        "--add-label",
                        "bug",
                        "--remove-label",
                        "afk:queued",
                        "--remove-label",
                        "afk:in-progress",
                    ],
                    "app-token",
                    id="adds and removes labels with the App's token",
                ),
                pytest.param(
                    EditLabels(number=7, remove=("afk:in-progress",)),
                    ["issue", "edit", "7", "--remove-label", "afk:in-progress"],
                    "app-token",
                    id="only removes labels when it adds none",
                ),
                pytest.param(
                    Comment(number=7, body="Hello `there`"),
                    ["issue", "comment", "7", "--body", "Hello `there`"],
                    "app-token",
                    id="comments with the App's token",
                ),
                pytest.param(
                    React(comment_id=555, content="eyes"),
                    [
                        "api",
                        "--method",
                        "POST",
                        "repos/{owner}/{repo}/issues/comments/555/reactions",
                        "-f",
                        "content=eyes",
                    ],
                    "app-token",
                    id="reacts to a comment with the App's token",
                ),
                pytest.param(
                    Unreact(comment_id=555, reaction_id=31),
                    [
                        "api",
                        "--method",
                        "DELETE",
                        "repos/{owner}/{repo}/issues/comments/555/reactions/31",
                    ],
                    "app-token",
                    id="removes a reaction with the App's token",
                ),
                pytest.param(
                    CreatePullRequest(
                        branch="afk/issue-7-100", title="feat: x", body="Closes #7"
                    ),
                    [
                        "pr",
                        "create",
                        "--draft",
                        "--base",
                        "main",
                        "--head",
                        "afk/issue-7-100",
                        "--title",
                        "feat: x",
                        "--body",
                        "Closes #7",
                    ],
                    "app-token",
                    id="opens a draft PR into main with the App's token",
                ),
                pytest.param(
                    EditPullRequest(
                        branch="afk/issue-7-100", title="feat: x", body="Closes #7"
                    ),
                    [
                        "pr",
                        "edit",
                        "afk/issue-7-100",
                        "--title",
                        "feat: x",
                        "--body",
                        "Closes #7",
                    ],
                    "app-token",
                    id="edits a branch's PR with the App's token",
                ),
                pytest.param(
                    EditPullRequestLabels(
                        branch="afk/issue-7-100",
                        add=("needs-car:copper",),
                        remove=("afk:blocked",),
                    ),
                    [
                        "pr",
                        "edit",
                        "afk/issue-7-100",
                        "--add-label",
                        "needs-car:copper",
                        "--remove-label",
                        "afk:blocked",
                    ],
                    "app-token",
                    id="adds and removes a branch's PR labels with the App's token",
                ),
                pytest.param(
                    MarkPullRequestReady(branch="afk/issue-7-100"),
                    ["pr", "ready", "afk/issue-7-100"],
                    "app-token",
                    id="marks a branch's PR ready with the App's token",
                ),
                pytest.param(
                    CommentPullRequest(branch="afk/issue-7-100", body="Covered."),
                    ["pr", "comment", "afk/issue-7-100", "--body", "Covered."],
                    "app-token",
                    id="comments on a branch's PR with the App's token",
                ),
                pytest.param(
                    CreateIssue(
                        title="Fix x", body="It breaks.", labels=("bug", "web")
                    ),
                    [
                        "issue",
                        "create",
                        "--title",
                        "Fix x",
                        "--body",
                        "It breaks.",
                        "--label",
                        "bug",
                        "--label",
                        "web",
                    ],
                    "app-token",
                    id="opens an issue with its labels with the App's token",
                ),
                pytest.param(
                    CloseIssue(number=7, comment="Implemented in abc123"),
                    ["issue", "close", "7", "--comment", "Implemented in abc123"],
                    "app-token",
                    id="closes an issue with a comment with the App's token",
                ),
                pytest.param(
                    ReplyToReviewComment(number=9, comment_id=501, body="Done."),
                    [
                        "api",
                        "--method",
                        "POST",
                        "repos/{owner}/{repo}/pulls/9/comments/501/replies",
                        "-f",
                        "body=Done.",
                    ],
                    "app-token",
                    id="replies in a PR's review thread with the App's token",
                ),
                pytest.param(
                    CreateReviewComment(
                        number=9,
                        commit="abc123",
                        path="docs/a.md",
                        line=4,
                        body="Note.",
                    ),
                    [
                        "api",
                        "--method",
                        "POST",
                        "repos/{owner}/{repo}/pulls/9/comments",
                        "-f",
                        "body=Note.",
                        "-f",
                        "commit_id=abc123",
                        "-f",
                        "path=docs/a.md",
                        "-F",
                        "line=4",
                        "-f",
                        "side=RIGHT",
                    ],
                    "app-token",
                    id="comments on a line of a PR's diff with the App's token",
                ),
            ],
        )
        def test_runs_each_gh_write_as_its_command_with_its_token(
            self, effect: Effect, args: list[str], token: str, tmp_path: Path
        ) -> None:
            gh = GhSpy()

            Writer(gh, GitSpy(), ENV, tmp_path / "output").write(effect)

            assert gh.calls == [GhCall(args, token, "owner/repo")]

        def test_pushes_head_with_the_app_s_token_for_github_only(
            self, tmp_path: Path
        ) -> None:
            gh, git = GhSpy(), GitSpy()

            Writer(gh, git, ENV, tmp_path / "output").write(
                PushBranch(repository="owner/repo", branch="afk/issue-7-100")
            )

            assert (gh.calls, git.calls) == (
                [],
                [
                    GitCall(
                        [
                            "-c",
                            "core.hooksPath=/dev/null",
                            "-c",
                            "credential.helper=",
                            "push",
                            "https://github.com/owner/repo.git",
                            "HEAD:refs/heads/afk/issue-7-100",
                        ],
                        {
                            "http.https://github.com/.extraheader": (
                                "AUTHORIZATION: basic eC1hY2Nlc3MtdG9rZW46YXBwLXRva2Vu"
                            )
                        },
                    )
                ],
            )

        def test_pushes_head_with_a_lease_on_the_branch_s_expected_head(
            self, tmp_path: Path
        ) -> None:
            git = GitSpy()

            Writer(GhSpy(), git, ENV, tmp_path / "output").write(
                PushBranch(repository="owner/repo", branch="feature", lease="head123")
            )

            assert git.calls[0].args == [
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "credential.helper=",
                "push",
                "--force-with-lease=refs/heads/feature:head123",
                "https://github.com/owner/repo.git",
                "HEAD:refs/heads/feature",
            ]

        def test_a_dry_run_runs_no_command(self, tmp_path: Path) -> None:
            gh, git = GhSpy(), GitSpy()
            env = {**ENV, "AFK_DRY_RUN": "true"}
            writer = Writer(gh, git, env, tmp_path / "output")

            # One of every kind of write.
            effects: list[Effect] = [
                DispatchWorkflow(workflow="afk-run.yml", inputs={"number": "7"}),
                EditLabels(number=7, add=("afk:in-progress",), remove=("afk:queued",)),
                Comment(number=7, body="Promoted."),
                React(comment_id=555, content="eyes"),
                PushBranch(repository="owner/repo", branch="afk/issue-7-100"),
                CreatePullRequest(
                    branch="afk/issue-7-100", title="feat: x", body="Closes #7"
                ),
                EditPullRequest(
                    branch="afk/issue-7-100", title="feat: x", body="Closes #7"
                ),
                EditPullRequestLabels(
                    branch="afk/issue-7-100", add=("needs-car:copper",)
                ),
                MarkPullRequestReady(branch="afk/issue-7-100"),
                CommentPullRequest(branch="afk/issue-7-100", body="Covered."),
                CreateIssue(title="Fix x", body="It breaks.", labels=("bug",)),
                CloseIssue(number=7, comment="Implemented in abc123"),
                PushBranch(repository="owner/repo", branch="feature", lease="head123"),
                ReplyToReviewComment(number=9, comment_id=501, body="Done."),
                CreateReviewComment(
                    number=9, commit="abc123", path="docs/a.md", line=4, body="Note."
                ),
            ]

            for effect in effects:
                writer.write(effect)

            assert (gh.calls, git.calls) == ([], [])

    class TestSetOutput:
        def test_appends_an_output_at_once(self, tmp_path: Path) -> None:
            output = tmp_path / "output"
            output.write_text("earlier=1\n")

            Writer(GhSpy(), GitSpy(), ENV, output).set_output("accepted", "true")

            lines = output.read_text().splitlines()
            delimiter = lines[1].removeprefix("accepted<<")
            assert lines == ["earlier=1", f"accepted<<{delimiter}", "true", delimiter]

    class TestReport:
        def test_a_dry_run_reports_its_writes_as_effects(self, tmp_path: Path) -> None:
            output = tmp_path / "output"
            writer = Writer(GhSpy(), GitSpy(), {**ENV, "AFK_DRY_RUN": "true"}, output)

            writer.write(
                DispatchWorkflow(workflow="afk-run.yml", inputs={"number": "7"})
            )
            writer.write(
                EditLabels(number=7, add=("afk:in-progress",), remove=("afk:queued",))
            )
            writer.write(Comment(number=7, body="Promoted."))
            writer.report()

            assert json.loads(read_outputs(output)["effects"]) == [
                {
                    "type": "DispatchWorkflow",
                    "workflow": "afk-run.yml",
                    "inputs": {"number": "7"},
                },
                {
                    "type": "EditLabels",
                    "number": 7,
                    "add": ["afk:in-progress"],
                    "remove": ["afk:queued"],
                },
                {"type": "Comment", "number": 7, "body": "Promoted."},
            ]

        def test_a_dry_run_with_no_writes_reports_no_effects(
            self, tmp_path: Path
        ) -> None:
            output = tmp_path / "output"

            Writer(GhSpy(), GitSpy(), {**ENV, "AFK_DRY_RUN": "true"}, output).report()

            assert read_outputs(output) == {"effects": "[]"}

        def test_a_real_run_reports_no_effects(self, tmp_path: Path) -> None:
            output = tmp_path / "output"
            writer = Writer(GhSpy(), GitSpy(), ENV, output)

            writer.write(Comment(number=7, body="Promoted."))
            writer.report()

            assert read_outputs(output) == {}


class TestWriteOutputs:
    def test_keeps_a_multiline_value_whole(self) -> None:
        output = io.StringIO()

        write_outputs(output, {"body": "first line\ninjected=1"})

        lines = output.getvalue().splitlines()
        delimiter = lines[0].removeprefix("body<<")
        assert lines == [f"body<<{delimiter}", "first line", "injected=1", delimiter]

    def test_uses_a_new_delimiter_for_each_write(self) -> None:
        output = io.StringIO()

        write_outputs(output, {"first": "1"})
        write_outputs(output, {"second": "2"})

        lines = output.getvalue().splitlines()
        assert lines[0].removeprefix("first<<") != lines[3].removeprefix("second<<")
