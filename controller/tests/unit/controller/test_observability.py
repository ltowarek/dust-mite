import logging
import threading
from collections.abc import Generator

import pytest
from opentelemetry.sdk._logs.export import (
    InMemoryLogRecordExporter,
    SimpleLogRecordProcessor,
)

import controller.logging
from controller.curses_logging import queued_console_logging
from controller.observability import ObservabilitySettings, configure_observability


class TestObservabilitySettingsFromEnv:
    @pytest.mark.parametrize(
        ("variable", "field"),
        [
            pytest.param(
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
                "traces_endpoint",
                id="traces_endpoint",
            ),
            pytest.param(
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "logs_endpoint", id="logs_endpoint"
            ),
            pytest.param(
                "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
                "metrics_endpoint",
                id="metrics_endpoint",
            ),
            pytest.param(
                "OTEL_EXPORTER_OTLP_PROFILES_ENDPOINT",
                "profiles_endpoint",
                id="profiles_endpoint",
            ),
            pytest.param("SERVICE_REPOSITORY", "repository", id="repository"),
        ],
    )
    def test_reads_each_variable_into_its_field(
        self, variable: str, field: str
    ) -> None:
        settings = ObservabilitySettings.from_env({variable: "http://example.invalid"})

        assert getattr(settings, field) == "http://example.invalid"

    @pytest.mark.parametrize(
        "field",
        [
            "traces_endpoint",
            "logs_endpoint",
            "metrics_endpoint",
            "profiles_endpoint",
            "repository",
        ],
    )
    def test_leaves_each_field_unset_without_its_variable(self, field: str) -> None:
        assert getattr(ObservabilitySettings.from_env({}), field) is None

    @pytest.mark.parametrize(
        ("field", "expected"),
        [
            pytest.param(
                "traces_endpoint", "http://collector.invalid/v1/traces", id="traces"
            ),
            pytest.param(
                "logs_endpoint", "http://collector.invalid/v1/logs", id="logs"
            ),
            pytest.param(
                "profiles_endpoint",
                "http://collector.invalid/v1development/profiles",
                id="profiles",
            ),
        ],
    )
    @pytest.mark.parametrize(
        "base",
        [
            pytest.param("http://collector.invalid", id="no_trailing_slash"),
            pytest.param("http://collector.invalid/", id="trailing_slash"),
        ],
    )
    def test_derives_signal_endpoints_from_the_base_endpoint(
        self, base: str, field: str, expected: str
    ) -> None:
        settings = ObservabilitySettings.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": base})

        assert getattr(settings, field) == expected

    def test_prefers_a_signal_endpoint_over_the_base_endpoint(self) -> None:
        settings = ObservabilitySettings.from_env(
            {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector.invalid",
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://tempo.invalid/traces",
            }
        )

        assert settings.traces_endpoint == "http://tempo.invalid/traces"

    def test_does_not_derive_the_metrics_endpoint_from_the_base_endpoint(self) -> None:
        """Metrics go straight to Mimir; the collector has no metrics pipeline."""
        settings = ObservabilitySettings.from_env(
            {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector.invalid"}
        )

        assert settings.metrics_endpoint is None

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            pytest.param("1", True, id="one"),
            pytest.param("0", False, id="zero"),
            pytest.param("true", False, id="non_canonical_spelling"),
            pytest.param("", False, id="empty"),
        ],
    )
    def test_enables_profiling_only_for_one(
        self, value: str, *, expected: bool
    ) -> None:
        settings = ObservabilitySettings.from_env({"PROFILING_ENABLED": value})

        assert settings.profiling_enabled is expected

    def test_leaves_profiling_disabled_without_its_variable(self) -> None:
        assert ObservabilitySettings.from_env({}).profiling_enabled is False


_LOGS_SETTINGS = ObservabilitySettings.from_env(
    {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://collector.invalid/v1/logs"}
)


@pytest.fixture
def exporter(monkeypatch: pytest.MonkeyPatch) -> InMemoryLogRecordExporter:
    """The in-memory exporter the logs endpoint exports to, synchronously."""
    log_exporter = InMemoryLogRecordExporter()  # type: ignore[no-untyped-call]  # the OpenTelemetry SDK leaves this constructor unannotated
    monkeypatch.setattr(controller.logging, "OTLPLogExporter", lambda **_: log_exporter)
    monkeypatch.setattr(
        controller.logging, "BatchLogRecordProcessor", SimpleLogRecordProcessor
    )
    return log_exporter


def _exported_bodies(exporter: InMemoryLogRecordExporter) -> list[object]:
    return [record.log_record.body for record in exporter.get_finished_logs()]


@pytest.fixture
def default_levels() -> Generator[None, None, None]:
    """Root and `controller` levels at their defaults, restored after the test.

    Importing pydualsense sets the root level to INFO.
    """
    root_logger, package_logger = logging.getLogger(), logging.getLogger("controller")
    root_level, package_level = root_logger.level, package_logger.level
    root_logger.setLevel(logging.WARNING)
    package_logger.setLevel(logging.NOTSET)
    yield
    root_logger.setLevel(root_level)
    package_logger.setLevel(package_level)


@pytest.fixture
def controller_logger() -> logging.Logger:
    return logging.getLogger("controller.test_module")


@pytest.mark.usefixtures("root_logger", "default_levels")
class TestConfigureObservabilityLogging:
    def test_writes_controller_debug_and_info_records_to_the_console(
        self, controller_logger: logging.Logger, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_observability("test-service", ObservabilitySettings.from_env({}))

        controller_logger.debug("debug detail")
        controller_logger.info("info detail")

        console = capsys.readouterr().err
        assert "DEBUG:controller.test_module:debug detail" in console
        assert "INFO:controller.test_module:info detail" in console

    def test_exports_controller_debug_and_info_records_and_writes_them_to_the_console(
        self,
        controller_logger: logging.Logger,
        exporter: InMemoryLogRecordExporter,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        configure_observability("test-service", _LOGS_SETTINGS)

        controller_logger.debug("debug detail")
        controller_logger.info("info detail")

        console = capsys.readouterr().err
        assert "DEBUG:controller.test_module:debug detail" in console
        assert "INFO:controller.test_module:info detail" in console
        exported = _exported_bodies(exporter)
        assert "debug detail" in exported
        assert "info detail" in exported

    def test_drops_third_party_records_below_warning(
        self, exporter: InMemoryLogRecordExporter, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_observability("test-service", _LOGS_SETTINGS)
        third_party_logger = logging.getLogger("websockets.test_module")

        third_party_logger.debug("debug detail")
        third_party_logger.info("info detail")
        third_party_logger.warning("warning detail")

        console = capsys.readouterr().err
        assert "debug detail" not in console
        assert "info detail" not in console
        assert "WARNING:websockets.test_module:warning detail" in console
        exported = _exported_bodies(exporter)
        assert "debug detail" not in exported
        assert "info detail" not in exported
        assert "warning detail" in exported

    def test_returns_a_console_handler_queued_console_logging_accepts(self) -> None:
        console_handler = configure_observability(
            "test-service", ObservabilitySettings.from_env({})
        )

        with queued_console_logging(console_handler):
            pass

    def test_writes_its_own_skipped_export_record_to_the_console(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_observability("test-service", ObservabilitySettings.from_env({}))

        assert "No OTLP logs endpoint, skipping log configuration" in (
            capsys.readouterr().err
        )


class TestConfigureObservability:
    def test_starts_no_profiler_without_a_profiles_endpoint(self) -> None:
        settings = ObservabilitySettings.from_env({"PROFILING_ENABLED": "1"})

        configure_observability("test-service", settings)

        assert "otlp-profiler-sampler" not in {t.name for t in threading.enumerate()}
