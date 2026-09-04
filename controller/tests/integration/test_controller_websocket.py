import dataclasses
import json
import threading
from collections.abc import Generator
from typing import Any

import pytest
import websockets.sync.server
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from controller.command import Command
from controller.senders import WebSocketCommandSender

_WAIT_TIMEOUT_S = 5


@dataclasses.dataclass
class LocalServer:
    server: websockets.sync.server.Server
    received: list[dict[str, Any]]
    message_received: threading.Event

    @property
    def uri(self) -> str:
        host, port = self.server.socket.getsockname()[:2]
        return f"ws://{host}:{port}"


@pytest.fixture
def local_server() -> Generator[LocalServer, None, None]:
    received: list[dict[str, Any]] = []
    message_received = threading.Event()

    def handler(websocket: websockets.sync.server.ServerConnection) -> None:
        message = websocket.recv()
        received.append(json.loads(message))
        message_received.set()

    with websockets.sync.server.serve(handler, "localhost", 0) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield LocalServer(server, received, message_received)
        finally:
            server.shutdown()
            thread.join()


def test_send_delivers_command_and_value_over_the_wire(
    local_server: LocalServer,
) -> None:
    sent_value = 50
    with WebSocketCommandSender(local_server.uri) as sender:
        sender.send(Command.ADVANCE, sent_value)
        assert local_server.message_received.wait(timeout=_WAIT_TIMEOUT_S)

    assert local_server.received[0]["command"] == Command.ADVANCE.value
    assert local_server.received[0]["value"] == sent_value


def test_send_injects_trace_context(local_server: LocalServer) -> None:
    # A local provider, never registered as the process-wide global one, so
    # this doesn't leak into other tests: `send`'s own tracer picks up the
    # active span's context from the ambient (contextvars-based) context
    # regardless of which provider created it.
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))
    tracer = provider.get_tracer(__name__)

    with tracer.start_as_current_span("outer") as outer_span:
        trace_id = outer_span.get_span_context().trace_id

        with WebSocketCommandSender(local_server.uri) as sender:
            sender.send(Command.BRAKE, None)
            assert local_server.message_received.wait(timeout=_WAIT_TIMEOUT_S)

    traceparent = local_server.received[0]["traceparent"]
    assert f"{trace_id:032x}" in traceparent
