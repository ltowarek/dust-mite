"""Guards what an AFK update-branch run pushes and comments after merging `main`."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from afk import update_branch_publish
from afk.effects import Comment, EditLabels, PushBranch
from afk.github import PullRequest
from afk.update_branch_merge import Merge
from afk.update_branch_publish import Merged, plan, unfinished
from afk.writer import Writer
from tests.test_doubles import GhSpy, GitSpy, read_outputs

RUN_URL = "https://github.com/owner/repo/actions/runs/77"
PR = PullRequest(number=9, branch="feature", head_sha="head123")
MERGED = Merged(main="main456", merge=Merge.CLEAN, run_url=RUN_URL)
PUSH = PushBranch(repository="owner/repo", branch="feature", lease="head123")


def conflict_output(**fields: object) -> dict[str, Any]:
    return {"conflict_summary": "Kept both lines.", "needs_dut_run": False, **fields}


class TestPlan:
    def test_comments_that_an_up_to_date_branch_needs_no_push(self) -> None:
        merged = replace(MERGED, merge=Merge.UP_TO_DATE)

        assert plan({}, PR, merged, repository="owner/repo") == [
            Comment(
                number=9,
                body="The branch already contains `main` (main456); this AFK run "
                f"pushed nothing.\n\n**Run:** {RUN_URL}\n",
            )
        ]

    def test_pushes_a_clean_merge_with_a_lease_on_the_pr_s_head(self) -> None:
        assert plan({}, PR, MERGED, repository="owner/repo") == [
            PUSH,
            Comment(
                number=9,
                body="Merged `main` (main456) into the branch with no conflicts."
                f"\n\n**Run:** {RUN_URL}\n",
            ),
        ]

    def test_comments_the_agent_s_resolution_and_the_follow_ups_already_covered(
        self,
    ) -> None:
        merged = replace(MERGED, merge=Merge.CONFLICT)
        output = conflict_output(
            already_covered=[{"problem": "The camera\n breaks.", "covered_by": 30}]
        )

        assert plan(output, PR, merged, repository="owner/repo") == [
            PUSH,
            Comment(
                number=9,
                body="> *Conflicts with `main` (main456) resolved by an AFK agent "
                f"session.* ([run]({RUN_URL}))\n\nKept both lines.\n"
                "\n## Follow-ups already covered\n\n"
                "- The camera breaks. Covered by #30.\n",
            ),
        ]

    def test_labels_the_pr_for_the_car_when_the_resolution_needs_a_dut_run(
        self,
    ) -> None:
        merged = replace(MERGED, merge=Merge.CONFLICT)
        output = conflict_output(needs_dut_run=True, car_variant="copper")

        assert plan(output, PR, merged, repository="owner/repo")[-1] == EditLabels(
            number=9, add=("needs-car:copper",)
        )


class TestUnfinished:
    @pytest.mark.parametrize(
        ("dirty", "merging", "contains", "error"),
        [
            pytest.param(
                True,
                False,
                True,
                "The working tree has uncommitted changes.",
                id="fails on uncommitted changes",
            ),
            pytest.param(
                False, True, True, "The merge is not committed.", id="fails mid-merge"
            ),
            pytest.param(
                False,
                False,
                False,
                "HEAD does not contain both the branch and main.",
                id="fails when HEAD lost the branch or main",
            ),
            pytest.param(False, False, True, None, id="passes a finished merge"),
        ],
    )
    def test_says_why_the_merge_is_unfinished(
        self, *, dirty: bool, merging: bool, contains: bool, error: str | None
    ) -> None:
        assert unfinished(dirty=dirty, merging=merging, contains=contains) == error


ENV = {
    "AFK_PR": "9",
    "AFK_BRANCH": "feature",
    "AFK_HEAD_SHA": "head123",
    "AFK_MAIN_SHA": "main456",
    "AFK_MERGE": "conflict",
    "AFK_AGENT_OUTCOME": "success",
    "AFK_AGENT_OUTPUT": json.dumps(conflict_output()),
    "AFK_APP_TOKEN": "app-token",
    "AFK_DRY_RUN": "true",
    "GH_REPO": "owner/repo",
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_RUN_ID": "77",
}
MERGE_HEAD = ("rev-parse", "-q", "--verify", "MERGE_HEAD")
CHANGED = ("--no-replace-objects", "log")


def publish(
    git: GitSpy, tmp_path: Path, **env: str
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    output = tmp_path / "output"
    merged_env = {**ENV, **env}
    writer = Writer(GhSpy(), git, merged_env, output)
    update_branch_publish.run(git, merged_env, writer)
    writer.report()
    outputs = read_outputs(output)
    return outputs, json.loads(outputs.get("effects", "null"))


def finished() -> GitSpy:
    # No MERGE_HEAD, and HEAD contains both the PR's head and main.
    return GitSpy({("rev-list", "--count"): "0\n"}, failing=MERGE_HEAD)


class TestRun:
    def test_reports_the_agent_s_error_after_a_failed_agent(
        self, tmp_path: Path
    ) -> None:
        outputs, _ = publish(finished(), tmp_path, AFK_AGENT_OUTCOME="failure")

        assert outputs == {"agent-error": "", "effects": "[]"}

    def test_lists_the_agent_s_files_with_remerge_beyond_the_pr_and_main(
        self, tmp_path: Path
    ) -> None:
        git = finished()

        publish(git, tmp_path)

        log = next(c.args for c in git.calls if tuple(c.args[:2]) == CHANGED)
        assert log[-5:] == [
            "--diff-merges=remerge",
            "HEAD",
            "--not",
            "head123",
            "main456",
        ]

    @pytest.mark.parametrize(
        "path",
        [
            pytest.param("tools/afk/src/afk/x.py", id="tools"),
            pytest.param(".github/workflows/x.yml", id="github"),
        ],
    )
    def test_refuses_an_agent_change_under_a_protected_path(
        self, tmp_path: Path, path: str
    ) -> None:
        git = GitSpy(
            {("rev-list", "--count"): "0\n", CHANGED: f"docs/a.md\0{path}\0"},
            failing=MERGE_HEAD,
        )

        with pytest.raises(SystemExit, match="Refused to publish"):
            publish(git, tmp_path)

    def test_fails_an_unfinished_merge_before_any_write(self, tmp_path: Path) -> None:
        git = GitSpy({("status",): " M docs/a.md\n", ("rev-list", "--count"): "0\n"})

        with pytest.raises(SystemExit, match="uncommitted changes"):
            publish(git, tmp_path, AFK_DRY_RUN="false")

        assert not any(c.args[2:3] == ["push"] for c in git.calls)

    def test_reads_neither_the_agent_nor_its_files_after_a_clean_merge(
        self, tmp_path: Path
    ) -> None:
        git = GitSpy()

        _, effects = publish(
            git, tmp_path, AFK_MERGE="clean", AFK_AGENT_OUTCOME="skipped"
        )

        assert git.calls == []
        assert [e["type"] for e in effects] == ["PushBranch", "Comment"]

    def test_plans_the_push_and_comment_after_a_resolved_conflict(
        self, tmp_path: Path
    ) -> None:
        _, effects = publish(finished(), tmp_path)

        assert effects[0] == {
            "type": "PushBranch",
            "repository": "owner/repo",
            "branch": "feature",
            "lease": "head123",
        }
        assert effects[1]["body"].startswith("> *Conflicts with `main` (main456)")
