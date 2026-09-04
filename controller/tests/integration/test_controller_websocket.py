from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from controller.command import Command
from controller.senders import WebSocketCommandSender

from .conftest import LocalServer

_WAIT_TIMEOUT_S = 5


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
