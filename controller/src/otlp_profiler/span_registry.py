"""Tracks the currently active span per thread for sample-to-span linking."""

import contextlib
import threading

from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor

_PROFILE_ID_ATTRIBUTE = "pyroscope.profile.id"

SpanContext = tuple[int, int]
"""(trace_id, span_id) of a span, both as plain ints."""


class ActiveSpanRegistry:
    """Thread-safe stack of active spans per thread.

    A `SpanProcessor` pushes/pops as spans start and end, and the sampler
    reads the top of each thread's stack to tag samples with whichever span
    is active on that thread at sample time. Nested spans on the same thread
    are handled correctly because each thread has its own stack.
    """

    def __init__(self) -> None:
        """Create an empty registry."""
        self._lock = threading.Lock()
        self._stacks: dict[int, list[SpanContext]] = {}
        self._owner_thread: dict[int, int] = {}

    def push(self, thread_id: int, trace_id: int, span_id: int) -> None:
        """Mark `(trace_id, span_id)` as the active span on `thread_id`."""
        with self._lock:
            self._stacks.setdefault(thread_id, []).append((trace_id, span_id))
            self._owner_thread[span_id] = thread_id

    def pop(self, span_id: int) -> None:
        """Undo a matching `push`, restoring the previous active span.

        Looks up the thread `span_id` was pushed on rather than trusting the
        caller's current thread -- a span started on one thread and ended on
        another (e.g. handed to an executor) must still be removed from its
        actual owning thread's stack, or that entry leaks forever.
        """
        with self._lock:
            thread_id = self._owner_thread.pop(span_id, None)
            if thread_id is None:
                return
            stack = self._stacks.get(thread_id)
            if not stack:
                return
            if stack[-1][1] == span_id:
                stack.pop()
            else:
                # Out-of-order end (shouldn't happen for correctly nested
                # spans); drop the stale entry rather than corrupt ordering.
                with contextlib.suppress(StopIteration):
                    index = next(
                        i for i, (_, sid) in enumerate(stack) if sid == span_id
                    )
                    del stack[index]
            if not stack:
                del self._stacks[thread_id]

    def current_span_context(self, thread_id: int) -> SpanContext | None:
        """Return the active (trace_id, span_id) on `thread_id`, or None if inactive."""
        with self._lock:
            stack = self._stacks.get(thread_id)
            return stack[-1] if stack else None


class SpanLinkingProcessor(SpanProcessor):
    """Stamps every span with a profile id and records it in a registry.

    Stamps every span, not just the root span of each trace, so per-span
    flame graphs work at any nesting depth.
    """

    def __init__(self, registry: ActiveSpanRegistry) -> None:
        """Create a processor that records active spans into `registry`."""
        self._registry = registry

    def on_start(
        self,
        span: Span,
        parent_context: Context | None = None,  # noqa: ARG002 -- required by base class
    ) -> None:
        """Record `span` as active on the current thread and stamp its profile id."""
        span_context = span.get_span_context()
        span.set_attribute(_PROFILE_ID_ATTRIBUTE, format(span_context.span_id, "016x"))
        self._registry.push(
            threading.get_ident(), span_context.trace_id, span_context.span_id
        )

    def on_end(self, span: ReadableSpan) -> None:
        """Remove `span` as the active span on its owning thread."""
        context = span.get_span_context()
        if context is None:
            return
        self._registry.pop(context.span_id)

    def shutdown(self) -> None:
        """No resources to release."""

    def force_flush(
        self,
        timeout_millis: int = 30000,  # noqa: ARG002 -- required by base class
    ) -> bool:
        """Nothing to flush; always succeeds."""
        return True
