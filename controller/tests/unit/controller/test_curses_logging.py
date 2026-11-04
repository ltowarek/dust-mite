import curses
import io
import logging
import logging.handlers
from typing import override

import pytest

from controller.curses_logging import (
    CursesHandler,
    LogWindow,
    queued_console_logging,
    queued_log_writer,
)


class WindowSpy(LogWindow):
    """Minimal stand-in for `curses.window`, recording calls made to it."""

    def __init__(self) -> None:
        self.written: list[str] = []
        self.scrollok_calls: list[bool] = []
        self.refresh_calls = 0

    @override
    def scrollok(self, flag: bool, /) -> None:
        self.scrollok_calls.append(flag)

    @override
    def addstr(self, text: str, /) -> None:
        self.written.append(text)

    @override
    def refresh(self) -> None:
        self.refresh_calls += 1


class RaisingWindowStub(LogWindow):
    """Stub `curses.window` whose every write raises `error`."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    @override
    def scrollok(self, flag: bool, /) -> None:
        """Accept the handler's scrolling setup."""

    @override
    def addstr(self, text: str, /) -> None:
        raise self._error

    @override
    def refresh(self) -> None:
        """Accept the handler's refresh."""


def _record(msg: str = "hello", args: tuple[object, ...] = ()) -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


@pytest.fixture
def window() -> WindowSpy:
    return WindowSpy()


class TestCursesHandler:
    def test_enables_scrolling_on_init(self, window: WindowSpy) -> None:
        CursesHandler(window)

        assert window.scrollok_calls == [True]

    def test_writes_formatted_message_with_trailing_newline(
        self, window: WindowSpy
    ) -> None:
        handler = CursesHandler(window)

        handler.emit(_record("hello %s", ("world",)))

        assert window.written == ["hello world\n"]

    def test_refreshes_after_writing(self, window: WindowSpy) -> None:
        handler = CursesHandler(window)

        handler.emit(_record())

        assert window.refresh_calls == 1

    def test_writes_consecutive_records_on_separate_lines(
        self, window: WindowSpy
    ) -> None:
        handler = CursesHandler(window)

        handler.emit(_record("first"))
        handler.emit(_record("second"))

        assert window.written == ["first\n", "second\n"]

    def test_swallows_curses_error_from_addstr(self) -> None:
        """The bottom-right-cell write raises `curses.error` even on success."""
        handler = CursesHandler(
            RaisingWindowStub(curses.error("add_wch() returned ERR"))
        )

        handler.emit(_record())  # must not raise

    def test_reports_any_other_error_through_handle_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        handler = CursesHandler(RaisingWindowStub(OSError("terminal is gone")))

        handler.emit(_record())

        assert "OSError: terminal is gone" in capsys.readouterr().err


class TestQueuedConsoleLogging:
    def test_raises_when_console_handler_is_not_attached(
        self, root_logger: logging.Logger
    ) -> None:
        """Failing loudly beats silently never queueing console output."""
        detached_handler = logging.StreamHandler()
        original_handlers = list(root_logger.handlers)

        with (
            pytest.raises(ValueError, match="not attached"),
            queued_console_logging(detached_handler),
        ):
            pass

        assert root_logger.handlers == original_handlers

    def test_swaps_console_handler_for_a_memory_handler(
        self, root_logger: logging.Logger
    ) -> None:
        console_handler = logging.StreamHandler()
        root_logger.addHandler(console_handler)

        with queued_console_logging(console_handler):
            assert console_handler not in root_logger.handlers
            assert any(
                isinstance(h, logging.handlers.MemoryHandler)
                for h in root_logger.handlers
            )

    def test_leaves_other_handlers_untouched(self, root_logger: logging.Logger) -> None:
        """The OpenTelemetry log bridge must keep exporting while curses owns
        the console handler."""
        console_handler = logging.StreamHandler()
        otel_handler = logging.NullHandler()
        root_logger.addHandler(console_handler)
        root_logger.addHandler(otel_handler)

        with queued_console_logging(console_handler):
            assert otel_handler in root_logger.handlers

    def test_restores_console_handler_on_exit(
        self, root_logger: logging.Logger
    ) -> None:
        console_handler = logging.StreamHandler()
        otel_handler = logging.NullHandler()
        root_logger.addHandler(console_handler)
        root_logger.addHandler(otel_handler)
        original_handlers = list(root_logger.handlers)

        with queued_console_logging(console_handler):
            pass

        assert root_logger.handlers == original_handlers

    def test_restores_console_handler_on_exception(
        self, root_logger: logging.Logger
    ) -> None:
        console_handler = logging.StreamHandler()
        root_logger.addHandler(console_handler)
        original_handlers = list(root_logger.handlers)
        error_message = "boom"

        with (
            pytest.raises(ValueError, match=error_message),
            queued_console_logging(console_handler),
        ):
            raise ValueError(error_message)

        assert root_logger.handlers == original_handlers

    def test_writes_records_still_queued_on_exit_to_the_console(
        self, root_logger: logging.Logger
    ) -> None:
        console = io.StringIO()
        console_handler = logging.StreamHandler(console)
        root_logger.addHandler(console_handler)
        logger = logging.getLogger("test-writes-left-over-records")
        logger.setLevel(logging.DEBUG)

        with queued_console_logging(console_handler):
            logger.info("left over")

        assert console.getvalue() == "left over\n"


class TestQueuedLogWriter:
    def test_holds_log_records_until_asked_to_write_them(
        self, window: WindowSpy, root_logger: logging.Logger
    ) -> None:
        console_handler = logging.StreamHandler(io.StringIO())
        root_logger.addHandler(console_handler)
        logger = logging.getLogger("test-holds-log-records")
        logger.setLevel(logging.DEBUG)

        with queued_console_logging(console_handler) as records:
            queued_log_writer(records, window, console_handler.formatter)
            logger.info("queued message")

        assert window.written == []

    def test_writes_queued_log_records_through_the_window(
        self, window: WindowSpy, root_logger: logging.Logger
    ) -> None:
        console_handler = logging.StreamHandler()
        root_logger.addHandler(console_handler)
        logger = logging.getLogger("test-writes-queued-records")
        logger.setLevel(logging.DEBUG)

        with queued_console_logging(console_handler) as records:
            write_queued_logs = queued_log_writer(
                records, window, console_handler.formatter
            )
            logger.info("routed message")
            write_queued_logs()

        assert window.written == ["routed message\n"]
