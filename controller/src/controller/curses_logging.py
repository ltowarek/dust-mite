"""Logging handler that writes through an active `curses` window."""

import contextlib
import curses
import logging
import logging.handlers
import sys
from collections.abc import Callable, Generator
from typing import Protocol, override


class LogWindow(Protocol):
    """The subset of `curses.window` this module writes through.

    A structural type rather than `curses.window` itself, so tests can pass
    a spy instead of a real (C-extension) curses window.
    """

    # `scrollok` and `addstr` mirror curses.window's C functions, which
    # only accept a positional bool/str, not a keyword.
    def scrollok(self, flag: bool, /) -> None:  # noqa: FBT001 - mirrors curses.window.scrollok's positional-only bool
        """Let the window scroll when the cursor moves past its last line."""

    def addstr(self, text: str, /) -> None:
        """Write `text` at the cursor."""

    def refresh(self) -> None:
        """Show what was written on the terminal."""


class CursesHandler(logging.Handler):
    r"""Write formatted log records through a `curses` window.

    A `StreamHandler` writes `\n`-terminated lines straight to the
    terminal, but under `curses` a bare `\n` doesn't return the cursor to
    column 0 the way a cooked-mode terminal does -- each line's start
    column then depends on where the previous line's cursor ended up,
    producing a staircase pattern. Writing through the window instead lets
    `curses` track the cursor and scroll correctly.
    """

    def __init__(self, window: LogWindow) -> None:
        """Initialize the handler and enable scrolling on `window`."""
        super().__init__()
        self._window = window
        self._window.scrollok(True)  # noqa: FBT003 - curses.window.scrollok takes only a positional bool

    @override
    def emit(self, record: logging.LogRecord) -> None:
        """Write the formatted `record` to the window."""
        try:
            self._window.addstr(self.format(record) + "\n")
            self._window.refresh()
        except curses.error:
            # Covers more than the one well-known curses quirk (writing
            # into the window's bottom-right cell raises even though the
            # character lands correctly) -- any `curses.error` here is
            # swallowed on purpose, because the only alternative,
            # `handleError`, writes raw text straight to the terminal and
            # would reproduce the exact staircase bug this handler exists
            # to prevent.
            pass
        except Exception:  # noqa: BLE001 - logging.Handler.emit must pass every exception to handleError
            self.handleError(record)


@contextlib.contextmanager
def queued_console_logging(
    console_handler: logging.Handler,
) -> Generator[logging.handlers.MemoryHandler, None, None]:
    """Buffer console output for the block; write what is left to the console on exit.

    Swaps `console_handler` out for a `MemoryHandler` on the root logger,
    leaving every other handler (e.g. the OpenTelemetry log bridge)
    untouched, and yields it.
    """
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    if console_handler not in original_handlers:
        msg = "console_handler is not attached to the root logger"
        raise ValueError(msg)
    # Never flushes on its own, so records are written only by whoever flushes it.
    buffer = logging.handlers.MemoryHandler(
        capacity=sys.maxsize, flushLevel=logging.CRITICAL + 1
    )
    root_logger.handlers = [
        buffer if handler is console_handler else handler
        for handler in original_handlers
    ]
    try:
        yield buffer
    finally:
        root_logger.handlers = original_handlers
        buffer.setTarget(console_handler)
        buffer.close()


def queued_log_writer(
    buffer: logging.handlers.MemoryHandler,
    window: LogWindow,
    formatter: logging.Formatter | None,
) -> Callable[[], None]:
    """Return a function that writes the records in `buffer` to `window`."""
    handler = CursesHandler(window)
    handler.setFormatter(formatter)
    buffer.setTarget(handler)
    return buffer.flush
