import pytest

from controller.observability import ObservabilitySettings


class TestObservabilitySettingsFromEnv:
    @pytest.mark.parametrize(
        ("variable", "field"),
        [
            pytest.param(
                "OTEL_EXPORTER_OTLP_ENDPOINT", "otlp_endpoint", id="otlp_endpoint"
            ),
            pytest.param(
                "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
                "metrics_endpoint",
                id="metrics_endpoint",
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
        "field", ["otlp_endpoint", "metrics_endpoint", "repository"]
    )
    def test_leaves_each_field_unset_without_its_variable(self, field: str) -> None:
        assert getattr(ObservabilitySettings.from_env({}), field) is None

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
