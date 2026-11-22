"""Guards how the agent's changed files are read from `git log`."""

from afk.git import changed_files


class TestChangedFiles:
    def test_reads_every_file_of_the_nul_separated_log_as_it_is(self) -> None:
        log = "docs/b c.md\0.github/workflows/é.yml\0docs/a.md\0"

        assert changed_files(log) == [
            "docs/b c.md",
            ".github/workflows/é.yml",
            "docs/a.md",
        ]
