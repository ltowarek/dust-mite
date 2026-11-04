"""Tracks the active span per asyncio task or thread for sample-to-span linking."""

import asyncio
import contextlib
import threading
import weakref
from collections.abc import Hashable
from typing import override

from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor

_PROFILE_ID_ATTRIBUTE = "pyroscope.profile.id"

SpanContext = tuple[int, int]
"""(trace_id, span_id) of a span, both as plain ints."""


class ActiveSpanRegistry:
    """Thread-safe stack of active spans per owner: an asyncio task, or else a thread.

    A `SpanProcessor` pushes/pops as spans start and end, and the sampler
    asks which span is active on a thread at sample time. While a registered
    event loop runs on that thread, only the span of the task it is running
    counts; otherwise the thread's own stack does.
    """

    def __init__(self) -> None:
        """Create an empty registry."""
        self._lock = threading.Lock()
        self._stacks: dict[Hashable, list[SpanContext]] = {}
        self._owners: dict[int, Hashable] = {}
        self._loops: weakref.WeakValueDictionary[int, asyncio.AbstractEventLoop] = (
            weakref.WeakValueDictionary()
        )

    def push(self, owner: Hashable, trace_id: int, span_id: int) -> None:
        """Mark `(trace_id, span_id)` active for `owner`, a task or a thread id."""
        with self._lock:
            self._stacks.setdefault(owner, []).append((trace_id, span_id))
            self._owners[span_id] = owner

    def register_loop(self, thread_id: int, loop: asyncio.AbstractEventLoop) -> None:
        """Record that `loop` runs on `thread_id`."""
        with self._lock:
            self._loops[thread_id] = loop

    def pop(self, span_id: int) -> None:
        """Undo a matching `push`, restoring the previous active span.

        Looks up the owner `span_id` was pushed for rather than trusting the
        caller -- a span started in one task or thread and ended in another
        must still be removed from its owner's stack, or that entry leaks.
        """
        with self._lock:
            owner = self._owners.pop(span_id, None)
            if owner is None:
                return
            stack = self._stacks.get(owner)
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
                del self._stacks[owner]

    def current_span_context(self, thread_id: int) -> SpanContext | None:
        """Return the active (trace_id, span_id) on `thread_id`, or None if inactive."""
        with self._lock:
            loop = self._loops.get(thread_id)
            owner: Hashable | None = thread_id
            if loop is not None and loop.is_running():
                owner = asyncio.current_task(loop)
            stack = self._stacks.get(owner) if owner is not None else None
            return stack[-1] if stack else None


class SpanLinkingProcessor(SpanProcessor):
    """Stamps every span with a profile id and records it in a registry.

    Stamps every span, not just the root span of each trace, so per-span
    flame graphs work at any nesting depth.
    """

    def __init__(self, registry: ActiveSpanRegistry) -> None:
        """Create a processor that records active spans into `registry`."""
        self._registry = registry

    @override
    def on_start(
        self,
        span: Span,
        parent_context: Context | None = None,
    ) -> None:
        """Record `span` as active in its task or thread; stamp its profile id."""
        span_context = span.get_span_context()
        span.set_attribute(_PROFILE_ID_ATTRIBUTE, format(span_context.span_id, "016x"))
        thread_id = threading.get_ident()
        owner: Hashable = thread_id
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            self._registry.register_loop(thread_id, loop)
            owner = asyncio.current_task(loop) or thread_id
        self._registry.push(owner, span_context.trace_id, span_context.span_id)

    @override
    def on_end(self, span: ReadableSpan) -> None:
        """Remove `span` as the active span of its owner."""
        context = span.get_span_context()
        if context is None:
            return
        self._registry.pop(context.span_id)

    @override
    def shutdown(self) -> None:
        """No resources to release."""

    @override
    def force_flush(
        self,
        timeout_millis: int = 30000,
    ) -> bool:
        """Nothing to flush; always succeeds."""
        return True
