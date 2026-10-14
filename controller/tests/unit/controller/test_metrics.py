from opentelemetry.sdk.metrics._internal.point import NumberDataPoint
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource

from controller.command import Command
from controller.metrics import (
    configure_metrics,
    record_command_blocked,
    record_command_sent,
    record_frame,
    record_telemetry_received,
)

from .conftest import counter_values_by_command


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

    assert counter_values_by_command(reader, "dust_mite_commands_sent") == {
        "TURN_LEFT": 1,
        "BRAKE": 2,
    }


def test_record_command_blocked_attributes_by_command_name(
    reader: InMemoryMetricReader,
) -> None:
    record_command_blocked(Command.ADVANCE)

    assert counter_values_by_command(reader, "dust_mite_commands_blocked") == {
        "ADVANCE": 1,
    }


def test_configure_metrics_skips_export_without_an_endpoint() -> None:
    configure_metrics(None, Resource.get_empty())

    record_command_sent(Command.BRAKE)
