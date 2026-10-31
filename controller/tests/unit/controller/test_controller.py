import asyncio
import io
import logging
import threading
from typing import override

import pytest

from controller.controller import ControllerSettings, _configure_console_logging
from controller.curses_logging import (
    LogWindow,
    queued_console_logging,
    queued_log_writer,
)
from controller.input_backends import InputBackendName, KeyboardInputBackend


class TestConfigureConsoleLogging:
    def test_attaches_a_stream_handler_to_the_root_logger(
        self, root_logger: logging.Logger
    ) -> None:
        handler = _configure_console_logging()

        assert handler in root_logger.handlers
        assert isinstance(handler, logging.StreamHandler)


class LoggingKeyboardWindowSpy(LogWindow):
    """Keyboard window whose every read logs from another thread, recording writes."""

    def __init__(self, keys: list[int], logger: logging.Logger) -> None:
        self._keys = iter(keys)
        self._logger = logger
        self._reads = 0
        self._reading = False
        self.written: list[str] = []
        self.writes_during_reads = 0

    def timeout(self, delay: int, /) -> None:
        """Accept the backend's read timeout."""

    def getch(self) -> int:
        self._reading = True
        self._reads += 1
        thread = threading.Thread(
            target=self._logger.info, args=("read %d", self._reads)
        )
        thread.start()
        thread.join()
        self._reading = False
        return next(self._keys)

    @override
    def scrollok(self, flag: bool, /) -> None:
        """Accept the handler's scrolling setup."""

    @override
    def addstr(self, text: str, /) -> None:
        self.writes_during_reads += self._reading
        self.written.append(text)

    @override
    def refresh(self) -> None:
        self.writes_during_reads += self._reading


class TestCursesLogging:
    @pytest.fixture
    def console(self) -> io.StringIO:
        return io.StringIO()

    @pytest.fixture
    def window(
        self, console: io.StringIO, root_logger: logging.Logger
    ) -> LoggingKeyboardWindowSpy:
        console_handler = logging.StreamHandler(console)
        root_logger.addHandler(console_handler)
        logger = logging.getLogger("test-curses-logging")
        logger.setLevel(logging.DEBUG)
        window = LoggingKeyboardWindowSpy([ord("a"), ord("q")], logger)
        with queued_console_logging(console_handler) as records:
            write_queued_logs = queued_log_writer(
                records, window, console_handler.formatter
            )
            backend = KeyboardInputBackend(window, write_queued_logs)
            asyncio.run(backend.read(lambda _: None))
        return window

    def test_writes_nothing_to_the_window_while_a_key_read_is_in_progress(
        self, window: LoggingKeyboardWindowSpy
    ) -> None:
        assert window.writes_during_reads == 0

    def test_writes_records_logged_from_another_thread_between_key_reads(
        self, window: LoggingKeyboardWindowSpy
    ) -> None:
        assert "read 1\n" in window.written

    @pytest.mark.usefixtures("window")
    def test_writes_a_record_logged_after_the_last_key_read_to_the_console(
        self, console: io.StringIO
    ) -> None:
        assert "read 2\n" in console.getvalue()


_CONTROLLER_ENV = {
    "STREAMER_DRIVE_URI": "ws://streamer.invalid/drive",
    "CONTROLLER_INPUT_BACKEND": "keyboard",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector.invalid",
}


class TestControllerSettingsFromEnv:
    def test_reads_the_streamer_drive_uri(self) -> None:
        settings = ControllerSettings.from_env(_CONTROLLER_ENV)

        assert settings.drive_uri == "ws://streamer.invalid/drive"

    def test_reads_the_input_backend(self) -> None:
        settings = ControllerSettings.from_env(_CONTROLLER_ENV)

        assert settings.input_backend is InputBackendName.KEYBOARD

    def test_reads_the_observability_settings(self) -> None:
        settings = ControllerSettings.from_env(_CONTROLLER_ENV)

        assert settings.observability.traces_endpoint == (
            "http://collector.invalid/v1/traces"
        )

    @pytest.mark.parametrize(
        "variable", ["STREAMER_DRIVE_URI", "CONTROLLER_INPUT_BACKEND"]
    )
    def test_requires_each_app_variable(self, variable: str) -> None:
        environ = {k: v for k, v in _CONTROLLER_ENV.items() if k != variable}

        with pytest.raises(KeyError, match=variable):
            ControllerSettings.from_env(environ)

    def test_rejects_an_unknown_input_backend(self) -> None:
        environ = {**_CONTROLLER_ENV, "CONTROLLER_INPUT_BACKEND": "joystick"}

        with pytest.raises(ValueError, match="joystick"):
            ControllerSettings.from_env(environ)
