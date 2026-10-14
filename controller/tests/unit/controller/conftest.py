import logging
from collections.abc import Generator

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics._internal.point import NumberDataPoint
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from controller.metrics import configure_metrics


@pytest.fixture
def root_logger() -> Generator[logging.Logger, None, None]:
    """The root logger, with its handler list restored after the test."""
    logger = logging.getLogger()
    original_handlers = list(logger.handlers)
    yield logger
    logger.handlers = original_handlers


@pytest.fixture
def reader() -> InMemoryMetricReader:
    metric_reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[metric_reader])
    configure_metrics("test-service", endpoint=None, provider=provider)
    return metric_reader


def counter_values_by_command(
    reader: InMemoryMetricReader, name: str
) -> dict[str, int]:
    data = reader.get_metrics_data()
    values: dict[str, int] = {}
    if data is None:
        return values
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name != name:
                    continue
                for dp in m.data.data_points:
                    if isinstance(dp, NumberDataPoint) and dp.attributes is not None:
                        key = str(dp.attributes["command.name"])
                        values[key] = values.get(key, 0) + int(dp.value)
    return values
