"""Guards how an AFK update-branch run merges `main` into the PR's head."""

import subprocess
from pathlib import Path

import pytest

from afk import update_branch_merge
from afk.writer import Writer
from tests.test_doubles import GhSpy, GitSpy, read_outputs

ENV = {
    "AFK_BOT_NAME": "afk[bot]",
    "AFK_BOT_ID": "900",
}
MAIN = ("rev-parse", "origin/main")
BEHIND = ("rev-list", "--count", "HEAD..origin/main")
MERGE = ("merge", "--no-edit", "origin/main")
UNMERGED = ("diff", "--name-only", "--diff-filter=U")


def merge(git: GitSpy, tmp_path: Path) -> dict[str, str]:
    output = tmp_path / "output"
    update_branch_merge.run(git, ENV, Writer(GhSpy(), git, ENV, output))
    return read_outputs(output)


class TestRun:
    def test_commits_as_the_app_s_bot(self, tmp_path: Path) -> None:
        git = GitSpy({BEHIND: "0\n"})

        merge(git, tmp_path)

        assert [c.args for c in git.calls[:2]] == [
            ["config", "user.name", "afk[bot]"],
            ["config", "user.email", "900+afk[bot]@users.noreply.github.com"],
        ]

    def test_merges_nothing_when_the_branch_already_contains_main(
        self, tmp_path: Path
    ) -> None:
        git = GitSpy({MAIN: "main123\n", BEHIND: "0\n"})

        assert merge(git, tmp_path) == {"main-sha": "main123", "merge": "up-to-date"}
        assert not any(c.args[0] == "merge" for c in git.calls)

    def test_merges_main_without_conflicts(self, tmp_path: Path) -> None:
        git = GitSpy({MAIN: "main123\n", BEHIND: "2\n"})

        assert merge(git, tmp_path) == {"main-sha": "main123", "merge": "clean"}
        assert ["merge", "--no-edit", "origin/main"] in [c.args for c in git.calls]

    def test_leaves_the_conflicts_for_the_agent(self, tmp_path: Path) -> None:
        git = GitSpy(
            {MAIN: "main123\n", BEHIND: "2\n", UNMERGED: "docs/a.md\n"}, failing=MERGE
        )

        assert merge(git, tmp_path) == {"main-sha": "main123", "merge": "conflict"}

    def test_fails_when_the_merge_fails_without_conflicts(self, tmp_path: Path) -> None:
        git = GitSpy({MAIN: "main123\n", BEHIND: "2\n"}, failing=MERGE)

        with pytest.raises(subprocess.CalledProcessError):
            merge(git, tmp_path)
