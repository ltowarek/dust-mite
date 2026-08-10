"""Background in-process CPU sampler.

Periodically snapshots every live thread's Python call stack via
`sys._current_frames()` and hands each sample to an `Aggregator`, tagged with
the sampled thread's name and (if any) currently active span id.

Samples are filtered to threads Linux reports as `R` (running) when their
`/proc/<tid>/stat` is read via `linux_thread_state.is_running` -- a few
microseconds after the `sys._current_frames()` snapshot, not at the exact
snapshot instant. This is state-only filtering, not state+GIL-ownership: a
thread spinning in `PyGILState_Ensure` waiting to acquire the GIL is
typically in `S` (blocked on futex), so it gets filtered out here even
though it's actively contending for CPU. That's an accepted limitation of
this iteration, not an oversight.
"""

import sys
import threading
import time
from collections.abc import Callable
from types import FrameType

from otlp_profiler import linux_thread_state
from otlp_profiler.aggregator import Aggregator, Stack
from otlp_profiler.span_registry import ActiveSpanRegistry

_THREAD_NAME_PREFIX = "otlp-profiler-"
_SAMPLER_THREAD_NAME = f"{_THREAD_NAME_PREFIX}sampler"
_EXPORT_THREAD_NAME = f"{_THREAD_NAME_PREFIX}export"


def walk_stack(frame: FrameType) -> Stack:
    """Build a leaf-first stack of (qualified name, filename, line number)."""
    entries = []
    current: FrameType | None = frame
    while current is not None:
        code = current.f_code
        entries.append((code.co_qualname, code.co_filename, current.f_lineno))
        current = current.f_back
    return tuple(entries)


class Sampler:
    """Owns the background sampling thread."""

    def __init__(
        self,
        aggregator: Aggregator,
        span_registry: ActiveSpanRegistry,
        sample_rate: int,
        export_interval_seconds: float,
        export_fn: Callable[[int], None],
    ) -> None:
        """Create a sampler; call `start()` to begin sampling."""
        self._aggregator = aggregator
        self._span_registry = span_registry
        self._interval_seconds = 1.0 / sample_rate
        self._export_interval_seconds = export_interval_seconds
        self._export_fn = export_fn
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._export_thread: threading.Thread | None = None
        self._thread_info: dict[int, tuple[str, int]] = {}

    def start(self) -> None:
        """Start the background sampling thread (idempotent)."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name=_SAMPLER_THREAD_NAME, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the background thread to stop and wait for it to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval_seconds * 10)

    def _run(self) -> None:
        window_start_ns = time.time_ns()
        next_export = time.monotonic() + self._export_interval_seconds
        while not self._stop_event.wait(self._interval_seconds):
            self._sample_once()
            if time.monotonic() >= next_export:
                # Export on its own thread so a slow/unreachable collector
                # (the export_fn does a blocking HTTP POST) doesn't stall
                # sampling ticks on this loop. Skip starting a new one while
                # the previous export is still in flight -- otherwise a slow
                # or unreachable collector piles up one export thread per
                # interval for as long as the outage lasts.
                if self._export_thread is None or not self._export_thread.is_alive():
                    self._export_thread = threading.Thread(
                        target=self._export_fn,
                        args=(window_start_ns,),
                        name=_EXPORT_THREAD_NAME,
                        daemon=True,
                    )
                    self._export_thread.start()
                next_export = time.monotonic() + self._export_interval_seconds
                window_start_ns = time.time_ns()

    def _rebuild_thread_info(self) -> None:
        self._thread_info = {
            t.ident: (t.name, t.native_id)
            for t in threading.enumerate()
            if t.ident is not None and t.native_id is not None
        }

    def _sample_once(self) -> None:
        frames = sys._current_frames()  # noqa: SLF001
        if not frames.keys() <= self._thread_info.keys():
            self._rebuild_thread_info()

        own_thread_ids = {self._thread.ident if self._thread else None}
        if self._export_thread is not None:
            own_thread_ids.add(self._export_thread.ident)

        for thread_id, frame in frames.items():
            if thread_id in own_thread_ids:
                continue
            info = self._thread_info.get(thread_id)
            if info is None:
                continue
            thread_name, native_id = info
            if not linux_thread_state.is_running(native_id):
                continue
            stack = walk_stack(frame)
            span_context = self._span_registry.current_span_context(thread_id)
            self._aggregator.add_sample(stack, thread_name, span_context)
