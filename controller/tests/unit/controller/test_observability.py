import logging
import threading
from collections.abc import Generator

import pytest
from opentelemetry.sdk.resources import Resource

import otlp_profiler
from controller.observability import ObservabilitySettings, configure_observability
from otlp_profiler.sampler import SAMPLER_THREAD_NAME, Sampler


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


@pytest.fixture
def package_level() -> Generator[None, None, None]:
    """The `controller` logger's level, restored after the test."""
    package_logger = logging.getLogger("controller")
    original_level = package_logger.level
    yield
    package_logger.setLevel(original_level)


@pytest.mark.usefixtures("root_logger", "package_level")
class TestConfigureObservabilityLogging:
    def test_writes_controller_debug_records_to_the_console(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_observability("test-service", ObservabilitySettings.from_env({}))

        logging.getLogger("controller.test_module").debug("debug detail")

        assert "DEBUG:controller.test_module:debug detail" in capsys.readouterr().err


@pytest.fixture
def stop_started_samplers(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Stop every sampler `otlp_profiler.configure` starts during the test."""
    started: list[Sampler] = []

    def configure(endpoint: str, resource: Resource) -> Sampler:
        sampler = original_configure(endpoint, resource)
        started.append(sampler)
        return sampler

    original_configure = otlp_profiler.configure
    monkeypatch.setattr(otlp_profiler, "configure", configure)
    yield
    for sampler in started:
        sampler.stop()


def _sampler_running() -> bool:
    return SAMPLER_THREAD_NAME in {t.name for t in threading.enumerate()}


class TestConfigureObservability:
    @pytest.mark.usefixtures("stop_started_samplers")
    def test_starts_the_profiler_with_a_profiles_endpoint(self) -> None:
        settings = ObservabilitySettings.from_env(
            {"OTEL_EXPORTER_OTLP_PROFILES_ENDPOINT": "http://127.0.0.1:9/profiles"}
        )

        configure_observability("test-service", settings)

        assert _sampler_running()

    def test_starts_no_profiler_without_a_profiles_endpoint(self) -> None:
        configure_observability("test-service", ObservabilitySettings.from_env({}))

        assert not _sampler_running()
