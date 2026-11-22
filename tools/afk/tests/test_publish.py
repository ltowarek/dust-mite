"""Guards what an AFK run publishes from the agent's structured output."""

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from afk import publish
from afk.effects import (
    Comment,
    CreatePullRequest,
    EditLabels,
    EditPullRequest,
    EditPullRequestLabels,
    Effect,
    MarkPullRequestReady,
    PushBranch,
)
from afk.publish import (
    Run,
    agent_error,
    changed_files,
    open_pull_request,
    plan,
    protected,
)
from afk.writer import Writer
from tests.test_doubles import GhSpy, GitCall, GitSpy, read_outputs

RUN = Run(
    repository="owner/repo",
    ticket=7,
    worked_ticket=8,
    branch="afk/issue-7-100",
    last_run=True,
    url="https://github.com/owner/repo/actions/runs/100",
)


def make_output(**fields: object) -> dict[str, Any]:
    return {
        "outcome": "done",
        "pr_title": "feat: add a thing",
        "pr_body": "Adds a thing.",
        "needs_dut_run": False,
        **fields,
    }


class TestPlan:
    class TestDone:
        def test_pushes_the_branch_and_opens_a_draft_pr_that_closes_the_ticket(
            self,
        ) -> None:
            effects = plan(make_output(), RUN, open_pr=None)

            assert effects[:2] == [
                PushBranch(repository="owner/repo", branch="afk/issue-7-100"),
                CreatePullRequest(
                    branch="afk/issue-7-100",
                    title="feat: add a thing",
                    body="Closes #7\n\nAdds a thing.\n\n"
                    "[AFK run](https://github.com/owner/repo/actions/runs/100)\n",
                ),
            ]

        def test_gives_an_open_pr_the_agent_s_title_and_body_on_the_last_run(
            self,
        ) -> None:
            effects = plan(
                make_output(), RUN, open_pr="https://github.com/owner/repo/pull/9"
            )

            assert effects[1] == EditPullRequest(
                branch="afk/issue-7-100",
                title="feat: add a thing",
                body="Closes #7\n\nAdds a thing.\n\n"
                "[AFK run](https://github.com/owner/repo/actions/runs/100)\n",
            )

        def test_leaves_an_open_pr_as_it_is_before_the_last_run(self) -> None:
            effects = plan(
                make_output(),
                replace(RUN, last_run=False),
                open_pr="https://github.com/owner/repo/pull/9",
            )

            assert effects == [
                PushBranch(repository="owner/repo", branch="afk/issue-7-100")
            ]

        @pytest.mark.parametrize(
            ("output", "last"),
            [
                pytest.param(
                    make_output(),
                    MarkPullRequestReady(branch="afk/issue-7-100"),
                    id="marks the PR ready when it needs no DUT run",
                ),
                pytest.param(
                    make_output(needs_dut_run=True, car_variant="copper"),
                    EditPullRequestLabels(
                        branch="afk/issue-7-100", add=("needs-car:copper",)
                    ),
                    id="labels the PR for the car when it needs a DUT run",
                ),
            ],
        )
        def test_hands_the_pr_on_after_the_last_run(
            self, output: dict[str, Any], last: Effect
        ) -> None:
            assert plan(output, RUN, open_pr=None)[-1] == last

        def test_leaves_a_new_pr_a_draft_before_the_last_run(self) -> None:
            effects = plan(make_output(), replace(RUN, last_run=False), open_pr=None)

            assert [type(effect) for effect in effects] == [
                PushBranch,
                CreatePullRequest,
            ]

    class TestNeedsCar:
        def test_labels_the_worked_ticket_for_the_car_and_comments_the_reason(
            self,
        ) -> None:
            output = {
                "outcome": "needs_car",
                "needs_dut_run": False,
                "car_variant": "copper",
                "needs_car_reason": "The motor stalls only on the car.",
            }

            assert plan(output, RUN, open_pr=None) == [
                EditLabels(number=8, add=("needs-car:copper",)),
                Comment(
                    number=8,
                    body="Finding the fix needs the car, so this AFK run pushed "
                    "nothing.\n\n**Reason:** The motor stalls only on the car."
                    "\n\n**Run:** https://github.com/owner/repo/actions/runs/100\n",
                ),
            ]

        def test_comments_an_empty_reason_when_the_agent_gives_none(self) -> None:
            output = {"outcome": "needs_car", "needs_dut_run": False}

            comment = plan(output, RUN, open_pr=None)[1]

            assert comment == Comment(
                number=8,
                body="Finding the fix needs the car, so this AFK run pushed nothing."
                "\n\n**Reason:** \n\n"
                "**Run:** https://github.com/owner/repo/actions/runs/100\n",
            )

    class TestSpecGap:
        def test_hands_the_worked_ticket_back_to_triage_with_the_gaps(self) -> None:
            output = {
                "outcome": "spec_gap",
                "needs_dut_run": False,
                "spec_gaps": "Which port?",
            }

            assert plan(output, RUN, open_pr=None) == [
                EditLabels(
                    number=8, add=("needs-triage",), remove=("ready-for-agent",)
                ),
                Comment(
                    number=8,
                    body="> *Spec gap found by an AFK agent session while working "
                    "this ticket.* ([run](https://github.com/owner/repo/actions/runs"
                    "/100))\n\nWhich port?\n",
                ),
            ]

        def test_hands_back_without_gaps_or_follow_ups_when_the_agent_gives_none(
            self,
        ) -> None:
            output = {
                "outcome": "spec_gap",
                "needs_dut_run": False,
                "already_covered": None,
            }

            comment = plan(output, RUN, open_pr=None)[1]

            assert comment == Comment(
                number=8,
                body="> *Spec gap found by an AFK agent session while working this "
                "ticket.* ([run](https://github.com/owner/repo/actions/runs/100))"
                "\n\n\n",
            )

        def test_lists_the_follow_ups_already_covered_on_one_line_each(
            self,
        ) -> None:
            output = {
                "outcome": "spec_gap",
                "needs_dut_run": False,
                "spec_gaps": "Which port?",
                "already_covered": [
                    {"problem": "The log\n   is noisy.", "covered_by": 12},
                    {"problem": "The test is slow.", "covered_by": 13},
                ],
            }

            comment = plan(output, RUN, open_pr=None)[1]

            assert comment == Comment(
                number=8,
                body="> *Spec gap found by an AFK agent session while working this "
                "ticket.* ([run](https://github.com/owner/repo/actions/runs/100))"
                "\n\nWhich port?\n\n## Follow-ups already covered\n\n"
                "- The log is noisy. Covered by #12.\n"
                "- The test is slow. Covered by #13.\n",
            )


class TestProtected:
    @pytest.mark.parametrize(
        ("paths", "expected"),
        [
            pytest.param(
                [".github/workflows/afk-run.yml", "docs/a.md"],
                [".github/workflows/afk-run.yml"],
                id="finds a file under .github/",
            ),
            pytest.param(
                ["tools/afk/src/afk/publish.py"],
                ["tools/afk/src/afk/publish.py"],
                id="finds a file under tools/",
            ),
            pytest.param(
                ["docs/tools/a.md", ".github-notes.md", "tools.md", "car/main.cpp"],
                [],
                id="ignores files outside both folders",
            ),
            pytest.param(
                ["tools/b.py", "tools/a.py", "tools/b.py"],
                ["tools/a.py", "tools/b.py"],
                id="lists each file once, in order",
            ),
        ],
    )
    def test_finds_the_changed_files_that_hold_the_write_token_s_code(
        self, paths: list[str], expected: list[str]
    ) -> None:
        assert protected(paths) == expected


class TestAgentError:
    @pytest.mark.parametrize(
        ("execution", "expected"),
        [
            pytest.param(
                [
                    {"type": "system"},
                    {"type": "result", "is_error": True, "result": "Out of turns."},
                ],
                "Out of turns.",
                id="reads the error that the agent's last message reports",
            ),
            pytest.param(
                [{"type": "result", "is_error": False, "result": "Done."}],
                "",
                id="reads nothing from a result that is no error",
            ),
            pytest.param(
                [
                    {"type": "result", "is_error": True, "result": "Old."},
                    {"type": "assistant"},
                ],
                "",
                id="reads nothing when the last message is no result",
            ),
            pytest.param(
                [{"type": "result", "is_error": True}],
                "",
                id="reads nothing from an error without a message",
            ),
            pytest.param([], "", id="reads nothing from an empty execution"),
        ],
    )
    def test_reads_the_agent_s_error(
        self, execution: list[dict[str, Any]], expected: str
    ) -> None:
        assert agent_error(execution) == expected


class TestChangedFiles:
    def test_reads_every_file_of_the_nul_separated_log_as_it_is(self) -> None:
        log = "docs/b c.md\0.github/workflows/é.yml\0docs/a.md\0"

        assert changed_files(log) == [
            "docs/b c.md",
            ".github/workflows/é.yml",
            "docs/a.md",
        ]


PR_URL = "https://github.com/owner/repo/pull/9"


class TestOpenPullRequest:
    @pytest.mark.parametrize(
        ("response", "expected"),
        [
            pytest.param([{"url": PR_URL}], PR_URL, id="reads the open PR's URL"),
            pytest.param([], None, id="reads no PR when the branch has none"),
        ],
    )
    def test_reads_the_branch_s_open_pr(
        self, response: list[dict[str, Any]], expected: str | None
    ) -> None:
        assert open_pull_request(response) == expected


ENV = {
    "AFK_AGENT_OUTCOME": "success",
    "AFK_AGENT_OUTPUT": json.dumps(make_output()),
    "AFK_APP_TOKEN": "app-token",
    "AFK_BASE": "base123",
    "AFK_BRANCH": "afk/issue-7-100",
    "AFK_LAST_RUN": "true",
    "AFK_TICKET": "7",
    "AFK_WORKED_TICKET": "8",
    "GH_REPO": "owner/repo",
    "GITHUB_RUN_ID": "100",
    "GITHUB_SERVER_URL": "https://github.com",
}
CHANGED_FILES_READ = (
    "git",
    "--no-replace-objects",
    "log",
    "-z",
    "--format=",
    "--name-only",
    "--no-renames",
    "--diff-merges=first-parent",
    "base123..HEAD",
)
OPEN_PR_READ = (
    "gh",
    "pr",
    "list",
    "--head",
    "afk/issue-7-100",
    "--state",
    "open",
    "--json",
    "url",
)
HEAD_READ = ("git", "rev-parse", "HEAD")
GH_READS: dict[tuple[str, ...], str] = {OPEN_PR_READ: json.dumps([{"url": PR_URL}])}
GIT_READS: dict[tuple[str, ...], str] = {
    CHANGED_FILES_READ: "docs/a.md\0",
    HEAD_READ: "abc123\n",
}


class TestRun:
    def test_refuses_commits_that_change_github_or_tools_and_writes_nothing(
        self, tmp_path: Path
    ) -> None:
        gh = GhSpy()
        git = GitSpy({CHANGED_FILES_READ: "docs/a.md\0.github/workflows/é.yml\0"})

        with pytest.raises(SystemExit, match=r"\.github/workflows/é\.yml"):
            publish.run(gh, git, ENV, Writer(gh, git, ENV, tmp_path / "output"))

        assert (gh.calls, git.calls) == ([], [GitCall(list(CHANGED_FILES_READ), "")])

    def test_reads_the_agent_s_commits_without_a_token(self, tmp_path: Path) -> None:
        gh, git = GhSpy(GH_READS), GitSpy(GIT_READS)

        publish.run(gh, git, ENV, Writer(gh, git, ENV, tmp_path / "output"))

        assert git.calls[0] == GitCall(list(CHANGED_FILES_READ), "")

    def test_reads_the_open_pr_with_the_app_token(self, tmp_path: Path) -> None:
        gh, git = GhSpy(GH_READS), GitSpy(GIT_READS)

        publish.run(gh, git, ENV, Writer(gh, git, ENV, tmp_path / "output"))

        assert {c.token for c in gh.calls if c.args[:3] == ["gh", "pr", "list"]} == {
            "app-token"
        }

    def test_sets_the_outcome_the_pr_the_head_and_the_planned_writes_as_outputs(
        self, tmp_path: Path
    ) -> None:
        gh, git = GhSpy(GH_READS), GitSpy(GIT_READS)
        env = {**ENV, "AFK_DRY_RUN": "true"}
        output = tmp_path / "output"
        writer = Writer(gh, git, env, output)

        publish.run(gh, git, env, writer)
        writer.report()

        assert read_outputs(output) == {
            "outcome": "done",
            "needs-car-reason": "",
            "pr-url": PR_URL,
            "sha": "abc123",
            "effects": json.dumps(
                [
                    {
                        "type": "PushBranch",
                        "repository": "owner/repo",
                        "branch": "afk/issue-7-100",
                    },
                    {
                        "type": "EditPullRequest",
                        "branch": "afk/issue-7-100",
                        "title": "feat: add a thing",
                        "body": "Closes #7\n\nAdds a thing.\n\n[AFK run]"
                        "(https://github.com/owner/repo/actions/runs/100)\n",
                    },
                    {"type": "MarkPullRequestReady", "branch": "afk/issue-7-100"},
                ]
            ),
        }

    def test_sets_the_outcome_before_a_push_that_fails(self, tmp_path: Path) -> None:
        gh, git = GhSpy(GH_READS), GitSpy(GIT_READS, failing=("git", "-c"))
        output = tmp_path / "output"

        with pytest.raises(subprocess.CalledProcessError):
            publish.run(gh, git, ENV, Writer(gh, git, ENV, output))

        assert read_outputs(output) == {"outcome": "done", "needs-car-reason": ""}

    def test_sets_no_pr_or_head_when_the_ticket_needs_the_car(
        self, tmp_path: Path
    ) -> None:
        agent_output = {
            "outcome": "needs_car",
            "needs_dut_run": False,
            "car_variant": "copper",
            "needs_car_reason": "Only on the car.",
        }
        env = {**ENV, "AFK_AGENT_OUTPUT": json.dumps(agent_output)}
        gh, git = GhSpy(), GitSpy({CHANGED_FILES_READ: ""})
        output = tmp_path / "output"

        publish.run(gh, git, env, Writer(gh, git, env, output))

        assert read_outputs(output) == {
            "outcome": "needs_car",
            "needs-car-reason": "Only on the car.",
        }

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
        output = tmp_path / "output"

        publish.run(gh, git, env, Writer(gh, git, env, output))

        assert (read_outputs(output), gh.calls, git.calls) == (
            {"agent-error": "Stuck."},
            [],
            [],
        )

    def test_after_an_agent_that_never_ran_sets_no_error(self, tmp_path: Path) -> None:
        env = {**ENV, "AFK_AGENT_OUTCOME": "skipped", "AFK_AGENT_OUTPUT": ""}
        gh, git = GhSpy(), GitSpy()
        output = tmp_path / "output"

        publish.run(gh, git, env, Writer(gh, git, env, output))

        assert read_outputs(output) == {"agent-error": ""}
