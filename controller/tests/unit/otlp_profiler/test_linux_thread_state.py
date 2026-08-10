import threading

from otlp_profiler import linux_thread_state


class TestParseState:
    def test_simple_running(self) -> None:
        raw = "123 (python) R 1 123 123 0 -1 4194560 0 0 0 0 0 0 0 0"
        assert linux_thread_state.parse_state(raw) == "R"

    def test_comm_with_space_is_not_split_on(self) -> None:
        raw = "123 (my thread) S 1 123 123 0 -1 4194560 0 0 0 0 0 0 0 0"
        assert linux_thread_state.parse_state(raw) == "S"

    def test_comm_with_nested_parens(self) -> None:
        raw = "123 (weird (name)) D 1 123 123 0 -1 4194560 0 0 0 0 0 0 0 0"
        assert linux_thread_state.parse_state(raw) == "D"

    def test_no_closing_paren_returns_none(self) -> None:
        assert linux_thread_state.parse_state("123 python R 1") is None

    def test_truncated_after_closing_paren_returns_none(self) -> None:
        assert linux_thread_state.parse_state("123 (python) ") is None


class TestIsRunning:
    def test_current_thread_returns_a_bool(self) -> None:
        result = linux_thread_state.is_running(threading.get_native_id())
        assert isinstance(result, bool)

    def test_nonexistent_tid_returns_none(self) -> None:
        assert linux_thread_state.is_running(2**30) is None
