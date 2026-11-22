"""Guards what `git` sees of the environment, and how the agent's changes are read."""

from afk.git import changed_files, run_git
from tests.test_doubles import GitCall, GitSpy


class TestRunGit:
    def test_runs_without_any_token_variable_and_authenticates_by_header(
        self,
    ) -> None:
        git = GitSpy()
        env = {"HOME": "/home/runner", "GH_TOKEN": "a", "CLAUDE_CODE_OAUTH_TOKEN": "b"}

        run_git(git, env, "secret", ["push"])

        assert git.calls == [
            GitCall(
                ["push"],
                {
                    "http.https://github.com/.extraheader": "AUTHORIZATION: basic "
                    "eC1hY2Nlc3MtdG9rZW46c2VjcmV0",
                },
            )
        ]


class TestChangedFiles:
    def test_reads_every_file_of_the_nul_separated_log_as_it_is(self) -> None:
        log = "docs/b c.md\0.github/workflows/é.yml\0docs/a.md\0"

        assert changed_files(log) == [
            "docs/b c.md",
            ".github/workflows/é.yml",
            "docs/a.md",
        ]
