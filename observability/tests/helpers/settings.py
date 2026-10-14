"""Addresses of the observability stack under test, read from the environment."""

import dataclasses
import os
from collections.abc import Mapping
from typing import Self


@dataclasses.dataclass(frozen=True)
class StackSettings:
    """Where the tests push signals and query them back."""

    grafana_url: str
    otlp_endpoint: str
    metrics_endpoint: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> Self:
        """Read the settings from `environ`, defaulting to the headless stack."""
        return cls(
            grafana_url=environ.get("GRAFANA_URL", "http://localhost:3000"),
            otlp_endpoint=environ.get(
                "OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318"
            ),
            metrics_endpoint=environ.get(
                "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
                "http://mimir:8080/otlp/v1/metrics",
            ),
        )


STACK_SETTINGS = StackSettings.from_env(os.environ)
