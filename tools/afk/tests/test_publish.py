"""Guards what an AFK run publishes from the agent's structured output."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from afk.effects import (
    AddPullRequestLabel,
    Comment,
    CreatePullRequest,
    EditLabels,
    EditPullRequest,
    Effect,
    MarkPullRequestReady,
    PushBranch,
)
from afk.publish import Run, agent_error, plan, protected, run
from afk.writer import Writer
from tests.test_doubles import read_outputs

RUN = Run(
    repository="owner/repo",
    ticket=7,
    worked_ticket=8,
    branch="afk/issue-7-100",
    last_run=True,
    url="https://github.com/owner/repo/actions/runs/100",
)


def done(**fields: object) -> dict[str, Any]:
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
            effects = plan(done(), RUN, open_pr=None)

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
            effects = plan(done(), RUN, open_pr="https://github.com/owner/repo/pull/9")

            assert effects[1] == EditPullRequest(
                branch="afk/issue-7-100",
                title="feat: add a thing",
                body="Closes #7\n\nAdds a thing.\n\n"
                "[AFK run](https://github.com/owner/repo/actions/runs/100)\n",
            )

        def test_leaves_an_open_pr_as_it_is_before_the_last_run(self) -> None:
            effects = plan(
                done(),
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
                    done(),
                    MarkPullRequestReady(branch="afk/issue-7-100"),
                    id="marks the PR ready when it needs no DUT run",
                ),
                pytest.param(
                    done(needs_dut_run=True, car_variant="copper"),
                    AddPullRequestLabel(
                        branch="afk/issue-7-100", label="needs-car:copper"
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
            effects = plan(done(), replace(RUN, last_run=False), open_pr=None)

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


PR_URL = "https://github.com/owner/repo/pull/9"


class RunnerSpy:
    """Answers the phase's reads like git and gh, and opens a PR on create."""

    def __init__(self, changed: str = "", open_pr: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self._changed = changed
        self._open_pr = open_pr

    def __call__(self, args: Sequence[str], _env: Mapping[str, str]) -> str:
        self.calls.append(list(args))
        match list(args):
            case ["git", "--no-replace-objects", "log", *_]:
                return self._changed
            case ["git", "rev-parse", "HEAD"]:
                return "abc123\n"
            case ["gh", "pr", "list", *_]:
                prs = [] if self._open_pr is None else [{"url": self._open_pr}]
                return json.dumps(prs)
            case ["gh", "pr", "create", *_]:
                self._open_pr = PR_URL
                return PR_URL + "\n"
            case _:
                return ""

    def wrote(self) -> bool:
        reads = (["git", "--no-replace-objects"], ["git", "rev-parse"], ["gh", "pr"])
        return any(
            call[:2] not in reads or call[:3] == ["gh", "pr", "create"]
            for call in self.calls
        )


def env(**overrides: str) -> dict[str, str]:
    return {
        "AFK_AGENT_OUTCOME": "success",
        "AFK_AGENT_OUTPUT": json.dumps(done()),
        "AFK_APP_TOKEN": "app-token",
        "AFK_BASE": "base123",
        "AFK_BRANCH": "afk/issue-7-100",
        "AFK_DRY_RUN": "true",
        "AFK_LAST_RUN": "true",
        "AFK_RUN_URL": "https://github.com/owner/repo/actions/runs/100",
        "AFK_TICKET": "7",
        "AFK_WORKED_TICKET": "8",
        "GH_REPO": "owner/repo",
        **overrides,
    }


def publish(runner: RunnerSpy, env: dict[str, str], tmp_path: Path) -> dict[str, str]:
    output = tmp_path / "output"
    writer = Writer(runner, env, output)
    run(runner, env, writer)
    writer.report()
    return read_outputs(output)


class TestRun:
    def test_refuses_commits_that_change_github_or_tools_and_writes_nothing(
        self, tmp_path: Path
    ) -> None:
        runner = RunnerSpy(changed="docs/a.md\0.github/workflows/é.yml\0")

        with pytest.raises(SystemExit, match=r"\.github/workflows/é\.yml"):
            publish(runner, env(AFK_DRY_RUN="false"), tmp_path)

        assert not runner.wrote()

    def test_reads_the_files_that_each_of_the_agent_s_commits_changes(
        self, tmp_path: Path
    ) -> None:
        runner = RunnerSpy()

        publish(runner, env(), tmp_path)

        assert runner.calls[0] == [
            "git",
            "--no-replace-objects",
            "log",
            "-z",
            "--format=",
            "--name-only",
            "--no-renames",
            "--diff-merges=first-parent",
            "base123..HEAD",
        ]

    def test_a_dry_run_reports_the_outcome_the_head_and_the_planned_writes(
        self, tmp_path: Path
    ) -> None:
        outputs = publish(RunnerSpy(open_pr=PR_URL), env(), tmp_path)

        assert outputs["outcome"] == "done"
        assert outputs["sha"] == "abc123"
        assert outputs["pr-url"] == PR_URL
        assert [e["type"] for e in json.loads(outputs["effects"])] == [
            "PushBranch",
            "EditPullRequest",
            "MarkPullRequestReady",
        ]

    def test_a_real_run_reports_the_pr_that_it_opened(self, tmp_path: Path) -> None:
        runner = RunnerSpy()

        outputs = publish(runner, env(AFK_DRY_RUN="false"), tmp_path)

        assert outputs == {
            "outcome": "done",
            "needs-car-reason": "",
            "pr-url": PR_URL,
            "sha": "abc123",
        }

    def test_reports_the_needs_car_reason_without_a_pr_or_head(
        self, tmp_path: Path
    ) -> None:
        output = {
            "outcome": "needs_car",
            "needs_dut_run": False,
            "car_variant": "copper",
            "needs_car_reason": "Only on the car.",
        }

        outputs = publish(
            RunnerSpy(), env(AFK_AGENT_OUTPUT=json.dumps(output)), tmp_path
        )

        assert {k: v for k, v in outputs.items() if k != "effects"} == {
            "outcome": "needs_car",
            "needs-car-reason": "Only on the car.",
        }

    def test_after_a_failed_agent_reports_its_error_and_nothing_else(
        self, tmp_path: Path
    ) -> None:
        execution = tmp_path / "execution.json"
        execution.write_text(
            json.dumps([{"type": "result", "is_error": True, "result": "Stuck."}])
        )
        runner = RunnerSpy()

        outputs = publish(
            runner,
            env(
                AFK_AGENT_OUTCOME="failure",
                AFK_AGENT_OUTPUT="",
                AFK_EXECUTION_FILE=str(execution),
                AFK_DRY_RUN="false",
            ),
            tmp_path,
        )

        assert (outputs, runner.calls) == ({"agent-error": "Stuck."}, [])

    def test_after_an_agent_that_never_ran_reports_no_error(
        self, tmp_path: Path
    ) -> None:
        outputs = publish(
            RunnerSpy(),
            env(AFK_AGENT_OUTCOME="skipped", AFK_AGENT_OUTPUT="", AFK_DRY_RUN="false"),
            tmp_path,
        )

        assert outputs == {"agent-error": ""}
