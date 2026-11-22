"""Guards which agent commits are refused, and how the agent's error is read."""

from typing import Any

import pytest

from afk.agent import agent_error, protected


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
