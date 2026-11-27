import threading

import pytest

from otlp_profiler import linux_thread_state


class TestParseState:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            pytest.param(
                "123 (python) R 1 123 123 0 -1 4194560 0 0 0 0 0 0 0 0",
                "R",
                id="simple running",
            ),
            pytest.param(
                "123 (my thread) S 1 123 123 0 -1 4194560 0 0 0 0 0 0 0 0",
                "S",
                id="comm with space is not split on",
            ),
            pytest.param(
                "123 (weird (name)) D 1 123 123 0 -1 4194560 0 0 0 0 0 0 0 0",
                "D",
                id="comm with nested parens",
            ),
            pytest.param("123 python R 1", None, id="no closing paren returns none"),
            pytest.param(
                "123 (python) ", None, id="truncated after closing paren returns none"
            ),
        ],
    )
    def test_parses_the_state(self, raw: str, expected: str | None) -> None:
        assert linux_thread_state.parse_state(raw) == expected


class TestIsRunning:
    def test_current_thread_returns_a_bool(self) -> None:
        result = linux_thread_state.is_running(threading.get_native_id())
        assert isinstance(result, bool)

    def test_nonexistent_tid_returns_none(self) -> None:
        assert linux_thread_state.is_running(2**30) is None
