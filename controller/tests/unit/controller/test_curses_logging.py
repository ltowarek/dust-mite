import curses
import logging

import pytest

from controller.curses_logging import CursesHandler, curses_console_logging


class FakeWindow:
    """Minimal stand-in for `curses.window`, recording calls made to it."""

    def __init__(self) -> None:
        self.written: list[str] = []
        self.scrollok_calls: list[bool] = []
        self.refresh_calls = 0

    def scrollok(self, flag: bool, /) -> None:  # noqa: FBT001 -- mirrors
        # curses.window.scrollok, a C function that only takes a positional bool
        self.scrollok_calls.append(flag)

    def addstr(self, text: str, /) -> None:
        self.written.append(text)

    def refresh(self) -> None:
        self.refresh_calls += 1


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
def window() -> FakeWindow:
    return FakeWindow()


class TestCursesHandler:
    def test_enables_scrolling_on_init(self, window: FakeWindow) -> None:
        CursesHandler(window)

        assert window.scrollok_calls == [True]

    def test_writes_formatted_message_with_trailing_newline(
        self, window: FakeWindow
    ) -> None:
        handler = CursesHandler(window)

        handler.emit(_record("hello %s", ("world",)))

        assert window.written == ["hello world\n"]

    def test_refreshes_after_writing(self, window: FakeWindow) -> None:
        handler = CursesHandler(window)

        handler.emit(_record())

        assert window.refresh_calls == 1

    def test_writes_consecutive_records_on_separate_lines(
        self, window: FakeWindow
    ) -> None:
        handler = CursesHandler(window)

        handler.emit(_record("first"))
        handler.emit(_record("second"))

        assert window.written == ["first\n", "second\n"]

    def test_swallows_curses_error_from_addstr(self) -> None:
        """The bottom-right-cell write raises `curses.error` even on success."""
        bottom_right_cell_error = curses.error("add_wch() returned ERR")

        class RaisingWindow(FakeWindow):
            def addstr(self, _text: str, /) -> None:
                raise bottom_right_cell_error

        handler = CursesHandler(RaisingWindow())

        handler.emit(_record())  # must not raise


class TestCursesConsoleLogging:
    def test_raises_when_console_handler_is_not_attached(
        self, window: FakeWindow, root_logger: logging.Logger
    ) -> None:
        """Failing loudly beats silently never swapping in `CursesHandler`."""
        detached_handler = logging.StreamHandler()
        original_handlers = list(root_logger.handlers)

        with (
            pytest.raises(ValueError, match="not attached"),
            curses_console_logging(window, detached_handler),
        ):
            pass

        assert root_logger.handlers == original_handlers

    def test_swaps_console_handler_for_a_curses_handler(
        self, window: FakeWindow, root_logger: logging.Logger
    ) -> None:
        console_handler = logging.StreamHandler()
        root_logger.addHandler(console_handler)

        with curses_console_logging(window, console_handler):
            assert console_handler not in root_logger.handlers
            assert any(isinstance(h, CursesHandler) for h in root_logger.handlers)

    def test_leaves_other_handlers_untouched(
        self, window: FakeWindow, root_logger: logging.Logger
    ) -> None:
        """The OpenTelemetry log bridge must keep exporting while curses owns
        the console handler."""
        console_handler = logging.StreamHandler()
        otel_handler = logging.NullHandler()
        root_logger.addHandler(console_handler)
        root_logger.addHandler(otel_handler)

        with curses_console_logging(window, console_handler):
            assert otel_handler in root_logger.handlers

    def test_restores_console_handler_on_exit(
        self, window: FakeWindow, root_logger: logging.Logger
    ) -> None:
        console_handler = logging.StreamHandler()
        otel_handler = logging.NullHandler()
        root_logger.addHandler(console_handler)
        root_logger.addHandler(otel_handler)
        original_handlers = list(root_logger.handlers)

        with curses_console_logging(window, console_handler):
            pass

        assert root_logger.handlers == original_handlers

    def test_restores_console_handler_on_exception(
        self, window: FakeWindow, root_logger: logging.Logger
    ) -> None:
        console_handler = logging.StreamHandler()
        root_logger.addHandler(console_handler)
        original_handlers = list(root_logger.handlers)
        error_message = "boom"

        with (
            pytest.raises(ValueError, match=error_message),
            curses_console_logging(window, console_handler),
        ):
            raise ValueError(error_message)

        assert root_logger.handlers == original_handlers

    def test_routes_log_records_through_the_window(
        self, window: FakeWindow, root_logger: logging.Logger
    ) -> None:
        console_handler = logging.StreamHandler()
        root_logger.addHandler(console_handler)
        logger = logging.getLogger("test-routes-through-window")
        logger.setLevel(logging.DEBUG)

        with curses_console_logging(window, console_handler):
            logger.info("routed message")

        assert window.written == ["routed message\n"]
