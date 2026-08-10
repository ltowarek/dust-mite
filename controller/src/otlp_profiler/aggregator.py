"""Aggregates sampled stacks into per-interval sample counts."""

import threading

StackFrame = tuple[str, str, int]
"""A single (qualified function name, filename, line number) frame."""

Stack = tuple[StackFrame, ...]
"""A leaf-first call stack."""

SpanContext = tuple[int, int]
"""(trace_id, span_id) of the active span, both as plain ints."""

SampleKey = tuple[Stack, str, SpanContext | None]
"""(stack, thread name, active span's (trace_id, span_id) or None)."""


class Aggregator:
    """Counts samples by (stack, thread name, span context) between drains."""

    def __init__(self) -> None:
        """Create an empty aggregator."""
        self._lock = threading.Lock()
        self._counts: dict[SampleKey, int] = {}

    def add_sample(
        self, stack: Stack, thread_name: str, span_context: SpanContext | None
    ) -> None:
        """Record one sample for the given stack/thread/span combination."""
        key = (stack, thread_name, span_context)
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + 1

    def drain(self) -> dict[SampleKey, int]:
        """Return accumulated counts and reset the aggregate to empty."""
        with self._lock:
            counts, self._counts = self._counts, {}
        return counts
