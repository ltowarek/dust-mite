"""Guards that samples taken on an event loop link to the span of the task it ran."""

import asyncio
import sys
import time
from collections.abc import Callable, Iterator

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Span

from otlp_profiler.aggregator import Aggregator, SampleKey
from otlp_profiler.sampler import Sampler
from otlp_profiler.span_registry import (
    ActiveSpanRegistry,
    SpanContext,
    SpanLinkingProcessor,
)

_SPIN_SECONDS = 0.5

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="on-CPU filtering is Linux-only"
)


def _spin() -> None:
    deadline = time.monotonic() + _SPIN_SECONDS
    while time.monotonic() < deadline:
        pass


@pytest.fixture
def aggregator() -> Aggregator:
    return Aggregator()


@pytest.fixture
def registry() -> ActiveSpanRegistry:
    return ActiveSpanRegistry()


@pytest.fixture
def provider(registry: ActiveSpanRegistry) -> TracerProvider:
    provider = TracerProvider()
    provider.add_span_processor(SpanLinkingProcessor(registry))
    return provider


@pytest.fixture
def sampler(aggregator: Aggregator, registry: ActiveSpanRegistry) -> Iterator[None]:
    sampler = Sampler(
        aggregator,
        registry,
        sample_rate=200,
        export_interval_seconds=100,
        export_fn=lambda _time_unix_nano: None,
    )
    sampler.start()
    try:
        yield
    finally:
        sampler.stop()


def _span_contexts_of(
    counts: dict[SampleKey, int], caller: Callable[..., object]
) -> set[SpanContext | None]:
    """Return the span contexts of every sample whose stack ran `caller`."""
    return {
        span_context
        for (stack, _thread_name, span_context) in counts
        if any(name == caller.__qualname__ for name, _file, _line in stack)
    }


def _span_context_of(span: Span) -> SpanContext:
    context = span.get_span_context()
    return context.trace_id, context.span_id


@pytest.mark.asyncio
@pytest.mark.usefixtures("sampler")
async def test_busy_task_samples_carry_its_span_not_a_later_suspended_one(
    aggregator: Aggregator, provider: TracerProvider
) -> None:
    tracer = provider.get_tracer(__name__)
    suspended_started = asyncio.Event()
    release_suspended = asyncio.Event()

    async def _suspended() -> None:
        with tracer.start_as_current_span("suspended"):
            suspended_started.set()
            await release_suspended.wait()

    async def _busy() -> SpanContext:
        with tracer.start_as_current_span("busy") as span:
            suspended = asyncio.create_task(_suspended())
            await suspended_started.wait()
            _spin()
            release_suspended.set()
            await suspended
            return _span_context_of(span)

    busy_span = await asyncio.create_task(_busy())

    assert _span_contexts_of(aggregator.drain(), _busy) == {busy_span}


@pytest.mark.asyncio
@pytest.mark.usefixtures("sampler")
async def test_worker_thread_samples_carry_the_span_started_there(
    aggregator: Aggregator, provider: TracerProvider
) -> None:
    tracer = provider.get_tracer(__name__)

    def _work() -> SpanContext:
        with tracer.start_as_current_span("worker") as span:
            _spin()
            return _span_context_of(span)

    worker_span = await asyncio.to_thread(_work)

    assert _span_contexts_of(aggregator.drain(), _work) == {worker_span}


@pytest.mark.asyncio
@pytest.mark.usefixtures("sampler")
async def test_callback_samples_carry_no_span(
    aggregator: Aggregator, provider: TracerProvider
) -> None:
    tracer = provider.get_tracer(__name__)
    callback_done = asyncio.Event()

    def _callback() -> None:
        _spin()
        callback_done.set()

    with tracer.start_as_current_span("waiting"):
        asyncio.get_running_loop().call_soon(_callback)
        await callback_done.wait()

    assert _span_contexts_of(aggregator.drain(), _callback) == {None}
