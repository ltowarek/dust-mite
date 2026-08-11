import pytest

from tests.helpers.query import TEMPO_UID, has_traces, query, traceql_query

# Excludes ws.stream.connection / ws.telemetry.connection / streamer.server_handler /
# ws.connection: these are long-lived, connection-scoped spans that only export
# when their socket closes, making "a recent trace exists" an unreliable check.
CASES = [
    ("dust-mite-car", "ws.stream.send"),
    ("dust-mite-car", "ws.telemetry.send"),
    ("dust-mite-car", "ws.command.receive"),
    ("dust-mite-streamer", "streamer.handle_camera_frame"),
    ("dust-mite-streamer", "streamer.process_frame"),
    ("dust-mite-streamer", "streamer.handle_telemetry"),
    ("dust-mite-streamer", "streamer.handle_drive_command"),
    ("dust-mite-web", "ws.message.receive.stream"),
    ("dust-mite-web", "ws.message.receive.telemetry"),
]


@pytest.mark.dut
@pytest.mark.parametrize(("service_name", "span_name"), CASES)
def test_service_has_recent_trace(service_name: str, span_name: str) -> None:
    assert has_traces(query(TEMPO_UID, "tempo", traceql_query(service_name, span_name)))
