"""Guards the AFK update-branch run's check: its mark and its refusals."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from afk import update_branch_check
from afk.github import PullRequest
from afk.update_branch_check import CheckResult, State, check, outputs
from afk.writer import Writer
from tests.test_doubles import GhSpy, GitSpy, read_outputs

PR = PullRequest(number=9, branch="feature", head_sha="head123")
STATE = State(
    pull_request=PR,
    url="https://github.com/owner/repo/pull/9",
    state="OPEN",
    fork=False,
)


class TestCheck:
    @pytest.mark.parametrize(
        ("state", "refusal"),
        [
            pytest.param(
                None,
                "Refused to run: this is not a PR, and `/afk update-branch` works "
                "only on a PR.",
                id="refuses an issue",
            ),
            pytest.param(
                replace(STATE, state="MERGED"),
                "Refused to run: this PR is merged.",
                id="refuses a merged PR",
            ),
            pytest.param(
                replace(STATE, state="CLOSED"),
                "Refused to run: this PR is closed.",
                id="refuses a closed PR",
            ),
            pytest.param(
                replace(STATE, fork=True),
                "Refused to run: this PR's branch is in a fork, and an AFK run never "
                "runs a fork's code with the repository's secrets.",
                id="refuses a PR whose branch is in a fork",
            ),
        ],
    )
    def test_refuses_the_run(self, state: State | None, refusal: str) -> None:
        assert check(state, head_sha="") == CheckResult(refusal=refusal)

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
        assert check(STATE, head_sha) == CheckResult(
            url="https://github.com/owner/repo/pull/9",
            pull_request=replace(PR, head_sha=expected),
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
                CheckResult(url="https://x/pull/9", pull_request=PR),
                {"url": "https://x/pull/9", "branch": "feature", "head-sha": "head123"},
                id="sets the PR of a run that goes ahead",
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
VIEW = {
    "number": 9,
    "state": "OPEN",
    "url": "https://github.com/owner/repo/pull/9",
    "isCrossRepository": False,
    "headRefName": "feature",
    "headRefOid": "head123",
}
PR_READS: dict[tuple[str, ...], str] = {
    ("api", "repos/owner/repo/issues/9"): json.dumps(
        {"number": 9, "pull_request": {"url": "https://api.github.com/x"}}
    ),
    ("pr", "view"): json.dumps(VIEW),
}


class TestRun:
    def test_marks_the_target_in_progress_before_its_reads(
        self, tmp_path: Path
    ) -> None:
        gh = GhSpy(PR_READS)

        update_branch_check.run(gh, ENV, Writer(gh, GitSpy(), ENV, tmp_path / "o"))

        assert [c.args[:2] for c in gh.calls] == [
            ["issue", "edit"],
            ["api", "repos/owner/repo/issues/9"],
            ["pr", "view"],
        ]
        assert {c.token for c in gh.calls[1:]} == {"workflow-token"}

    def test_refuses_an_issue_without_reading_a_pr(self, tmp_path: Path) -> None:
        gh = GhSpy({("api",): json.dumps({"number": 9})})
        output = tmp_path / "output"

        update_branch_check.run(gh, ENV, Writer(gh, GitSpy(), ENV, output))

        assert [c.args[0] for c in gh.calls] == ["issue", "api"]
        assert read_outputs(output)["refusal"].startswith(
            "Refused to run: this is not a PR"
        )

    def test_sets_the_decision_and_the_planned_mark_as_outputs(
        self, tmp_path: Path
    ) -> None:
        gh = GhSpy(PR_READS)
        env = {**ENV, "AFK_DRY_RUN": "true"}
        output = tmp_path / "output"
        writer = Writer(gh, GitSpy(), env, output)

        update_branch_check.run(gh, env, writer)
        writer.report()

        assert read_outputs(output) == {
            "url": "https://github.com/owner/repo/pull/9",
            "branch": "feature",
            "head-sha": "head123",
            "effects": '[{"type": "EditLabels", "number": 9, '
            '"add": ["afk:in-progress"], "remove": []}]',
        }
