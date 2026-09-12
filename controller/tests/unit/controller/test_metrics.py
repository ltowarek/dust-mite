import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics._internal.point import NumberDataPoint
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from controller.command import Command
from controller.metrics import (
    configure_metrics,
    record_command_sent,
    record_frame,
    record_telemetry_received,
)


def _counter_values_by_command(
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


def _counter_value(reader: InMemoryMetricReader, name: str) -> int:
    data = reader.get_metrics_data()
    if data is None:
        return 0
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name == name:
                    return int(
                        sum(
                            dp.value
                            for dp in m.data.data_points
                            if isinstance(dp, NumberDataPoint)
                        )
                    )
    return 0


@pytest.fixture
def reader() -> InMemoryMetricReader:
    metric_reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[metric_reader])
    configure_metrics("test-service", provider=provider)
    return metric_reader


def test_record_frame(reader: InMemoryMetricReader) -> None:
    calls = 2
    for _ in range(calls):
        record_frame()
    assert _counter_value(reader, "dust_mite_frames_processed") == calls


def test_record_telemetry_received(reader: InMemoryMetricReader) -> None:
    record_telemetry_received()
    assert _counter_value(reader, "dust_mite_telemetry_packets_received") == 1


def test_record_command_sent(reader: InMemoryMetricReader) -> None:
    calls = 3
    for _ in range(calls):
        record_command_sent(Command.BRAKE)
    assert _counter_value(reader, "dust_mite_commands_sent") == calls


def test_record_command_sent_attributes_by_command_name(
    reader: InMemoryMetricReader,
) -> None:
    record_command_sent(Command.TURN_LEFT)
    record_command_sent(Command.BRAKE)
    record_command_sent(Command.BRAKE)

    assert _counter_values_by_command(reader, "dust_mite_commands_sent") == {
        "TURN_LEFT": 1,
        "BRAKE": 2,
    }


def test_configure_metrics_skips_export_without_an_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", raising=False)

    configure_metrics("test-service")

    record_command_sent(Command.BRAKE)
