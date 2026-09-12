"""Logging handler that writes through an active `curses` window."""

import contextlib
import curses
import logging
from collections.abc import Generator
from typing import Protocol


class _LogWindow(Protocol):
    """The subset of `curses.window` this module writes through.

    A structural type rather than `curses.window` itself, so tests can pass
    a plain fake instead of a real (C-extension) curses window.
    """

    # `scrollok` and `addstr` mirror curses.window's C functions, which
    # only accept a positional bool/str, not a keyword.
    def scrollok(self, flag: bool, /) -> None: ...  # noqa: FBT001
    def addstr(self, text: str, /) -> None: ...
    def refresh(self) -> None: ...


class CursesHandler(logging.Handler):
    r"""Write formatted log records through a `curses` window.

    A `StreamHandler` writes `\n`-terminated lines straight to the
    terminal, but under `curses` a bare `\n` doesn't return the cursor to
    column 0 the way a cooked-mode terminal does -- each line's start
    column then depends on where the previous line's cursor ended up,
    producing a staircase pattern. Writing through the window instead lets
    `curses` track the cursor and scroll correctly.
    """

    def __init__(self, window: _LogWindow) -> None:
        """Initialize the handler and enable scrolling on `window`."""
        super().__init__()
        self._window = window
        self._window.scrollok(True)  # noqa: FBT003 -- positional-only, see above

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
        except Exception:  # noqa: BLE001 -- never let a broken handler crash the caller
            self.handleError(record)


@contextlib.contextmanager
def curses_console_logging(
    window: _LogWindow, console_handler: logging.Handler
) -> Generator[None, None, None]:
    """Route console output through `window` for the duration of the block.

    Swaps `console_handler` out for a `CursesHandler` on the root logger,
    leaving every other handler (e.g. the OpenTelemetry log bridge)
    untouched, and restores `console_handler` on exit.
    """
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    if console_handler not in original_handlers:
        msg = "console_handler is not attached to the root logger"
        raise ValueError(msg)
    curses_handler = CursesHandler(window)
    curses_handler.setFormatter(console_handler.formatter)
    root_logger.handlers = [
        curses_handler if handler is console_handler else handler
        for handler in original_handlers
    ]
    try:
        yield
    finally:
        root_logger.handlers = original_handlers
