import logging
import threading

import pytest

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


class TestConfigureObservability:
    def test_sets_up_no_log_export_without_endpoints(
        self, root_logger: logging.Logger
    ) -> None:
        original_handlers = list(root_logger.handlers)

        configure_observability("test-service", ObservabilitySettings.from_env({}))

        assert root_logger.handlers == original_handlers

    def test_starts_no_profiler_without_a_profiles_endpoint(self) -> None:
        settings = ObservabilitySettings.from_env({"PROFILING_ENABLED": "1"})

        configure_observability("test-service", settings)

        assert "otlp-profiler-sampler" not in {t.name for t in threading.enumerate()}
