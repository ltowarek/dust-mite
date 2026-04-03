import opentelemetry.trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from controller.tracing import extract_trace_context, inject_trace_context


def _make_provider() -> TracerProvider:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider


class TestInjectTraceContext:
    def test_adds_traceparent(self) -> None:
        provider = _make_provider()
        opentelemetry.trace.set_tracer_provider(provider)
        tracer = opentelemetry.trace.get_tracer(__name__)

        payload = {"command": 3, "value": 50}
        with tracer.start_as_current_span("test-span"):
            result = inject_trace_context(payload)

        assert "traceparent" in result
        assert result["command"] == payload["command"]

    def test_preserves_existing_keys(self) -> None:
        provider = _make_provider()
        opentelemetry.trace.set_tracer_provider(provider)
        tracer = opentelemetry.trace.get_tracer(__name__)

        payload = {"command": 3, "value": 50}
        with tracer.start_as_current_span("test-span"):
            result = inject_trace_context(payload)

        assert result["command"] == payload["command"]
        assert result["value"] == payload["value"]

    def test_returns_copy(self) -> None:
        provider = _make_provider()
        opentelemetry.trace.set_tracer_provider(provider)
        tracer = opentelemetry.trace.get_tracer(__name__)

        original = {"command": 1}
        with tracer.start_as_current_span("test-span"):
            result = inject_trace_context(original)

        assert "traceparent" not in original
        assert "traceparent" in result


class TestExtractTraceContext:
    def test_recovers_span(self) -> None:
        provider = _make_provider()
        opentelemetry.trace.set_tracer_provider(provider)
        tracer = opentelemetry.trace.get_tracer(__name__)

        with tracer.start_as_current_span("sender-span") as span:
            payload = inject_trace_context({"command": 1})
            sent_trace_id = span.get_span_context().trace_id

        extracted_ctx = extract_trace_context(payload)
        span_ctx = opentelemetry.trace.get_current_span(
            extracted_ctx
        ).get_span_context()

        assert span_ctx.trace_id == sent_trace_id

    def test_with_no_traceparent_returns_empty_context(self) -> None:
        result = extract_trace_context({"command": 1, "value": 50})
        propagator = TraceContextTextMapPropagator()
        carrier: dict[str, str] = {}
        propagator.inject(carrier, context=result)
        assert "traceparent" not in carrier
