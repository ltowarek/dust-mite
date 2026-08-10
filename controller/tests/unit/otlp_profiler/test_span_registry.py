import threading

from opentelemetry.sdk.trace import Span, TracerProvider

from otlp_profiler.span_registry import ActiveSpanRegistry, SpanLinkingProcessor

_TRACE_ID = 1
_SPAN_ID_A = 100
_SPAN_ID_B = 200


class TestActiveSpanRegistry:
    def test_push_then_current_span_context_returns_it(self) -> None:
        registry = ActiveSpanRegistry()
        registry.push(1, _TRACE_ID, _SPAN_ID_A)

        assert registry.current_span_context(1) == (_TRACE_ID, _SPAN_ID_A)

    def test_nested_push_returns_innermost(self) -> None:
        registry = ActiveSpanRegistry()
        registry.push(1, _TRACE_ID, _SPAN_ID_A)
        registry.push(1, _TRACE_ID, _SPAN_ID_B)

        assert registry.current_span_context(1) == (_TRACE_ID, _SPAN_ID_B)

    def test_pop_restores_previous_span(self) -> None:
        registry = ActiveSpanRegistry()
        registry.push(1, _TRACE_ID, _SPAN_ID_A)
        registry.push(1, _TRACE_ID, _SPAN_ID_B)

        registry.pop(_SPAN_ID_B)

        assert registry.current_span_context(1) == (_TRACE_ID, _SPAN_ID_A)

    def test_pop_last_span_clears_thread(self) -> None:
        registry = ActiveSpanRegistry()
        registry.push(1, _TRACE_ID, _SPAN_ID_A)

        registry.pop(_SPAN_ID_A)

        assert registry.current_span_context(1) is None

    def test_pop_finds_the_owning_thread_regardless_of_caller(self) -> None:
        # A span pushed on thread 1 but ended from a different thread (e.g.
        # handed to an executor) must still be removed from thread 1's
        # stack. pop() takes no thread_id, so the only way to actually
        # exercise "a different calling thread" is a real second thread.
        registry = ActiveSpanRegistry()
        registry.push(1, _TRACE_ID, _SPAN_ID_A)

        popping_thread = threading.Thread(target=registry.pop, args=(_SPAN_ID_A,))
        popping_thread.start()
        popping_thread.join()

        assert registry.current_span_context(1) is None

    def test_unknown_thread_returns_none(self) -> None:
        registry = ActiveSpanRegistry()

        assert registry.current_span_context(999) is None

    def test_threads_are_independent(self) -> None:
        registry = ActiveSpanRegistry()
        registry.push(1, _TRACE_ID, _SPAN_ID_A)
        registry.push(2, _TRACE_ID, _SPAN_ID_B)

        assert registry.current_span_context(1) == (_TRACE_ID, _SPAN_ID_A)
        assert registry.current_span_context(2) == (_TRACE_ID, _SPAN_ID_B)


class TestSpanLinkingProcessor:
    def test_stamps_profile_id_and_registers_span(self) -> None:
        registry = ActiveSpanRegistry()
        provider = TracerProvider()
        provider.add_span_processor(SpanLinkingProcessor(registry))
        tracer = provider.get_tracer(__name__)
        thread_id = threading.get_ident()

        with tracer.start_as_current_span("op") as span:
            assert isinstance(span, Span)
            span_context = span.get_span_context()
            assert registry.current_span_context(thread_id) == (
                span_context.trace_id,
                span_context.span_id,
            )
            assert span.attributes is not None
            assert span.attributes["pyroscope.profile.id"] == format(
                span_context.span_id, "016x"
            )

        assert registry.current_span_context(thread_id) is None

    def test_nested_spans_stamp_and_restore_correctly(self) -> None:
        registry = ActiveSpanRegistry()
        provider = TracerProvider()
        provider.add_span_processor(SpanLinkingProcessor(registry))
        tracer = provider.get_tracer(__name__)
        thread_id = threading.get_ident()

        with tracer.start_as_current_span("outer") as outer:
            outer_context = outer.get_span_context()
            with tracer.start_as_current_span("inner") as inner:
                inner_context = inner.get_span_context()
                assert registry.current_span_context(thread_id) == (
                    inner_context.trace_id,
                    inner_context.span_id,
                )
            assert registry.current_span_context(thread_id) == (
                outer_context.trace_id,
                outer_context.span_id,
            )

        assert registry.current_span_context(thread_id) is None
