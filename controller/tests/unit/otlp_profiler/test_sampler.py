import sys
import threading
import time

import pytest

from otlp_profiler.aggregator import Aggregator, SampleKey
from otlp_profiler.sampler import Sampler, walk_stack
from otlp_profiler.span_registry import ActiveSpanRegistry


def _inner() -> tuple[tuple[str, str, int], ...]:
    frame = sys._current_frames()[threading.get_ident()]  # noqa: SLF001
    return walk_stack(frame)


def _outer() -> tuple[tuple[str, str, int], ...]:
    return _inner()


class TestWalkStack:
    def test_returns_leaf_first_qualified_names(self) -> None:
        stack = _outer()

        names = [entry[0] for entry in stack]
        assert names[0] == "_inner"
        assert "_outer" in names
        assert names.index("_inner") < names.index("_outer")

    def test_entries_are_hashable_tuples(self) -> None:
        frame_entry_field_count = 3
        stack = _outer()

        assert isinstance(stack, tuple)
        assert all(
            isinstance(entry, tuple) and len(entry) == frame_entry_field_count
            for entry in stack
        )


class TestSampler:
    @pytest.mark.skipif(
        sys.platform != "linux", reason="on-CPU filtering is Linux-only"
    )
    def test_samples_are_recorded_while_running(self) -> None:
        aggregator = Aggregator()
        registry = ActiveSpanRegistry()
        sampler = Sampler(
            aggregator,
            registry,
            sample_rate=200,
            export_interval_seconds=100,
            export_fn=lambda _time_unix_nano: None,
        )

        sampler.start()
        try:
            deadline = time.monotonic() + 2
            counts: dict[SampleKey, int] = {}
            while time.monotonic() < deadline and not counts:
                time.sleep(0.05)
                counts = aggregator.drain()
        finally:
            sampler.stop()

        assert counts

    def test_export_fn_is_invoked_after_export_interval(self) -> None:
        aggregator = Aggregator()
        registry = ActiveSpanRegistry()
        export_calls = []
        sampler = Sampler(
            aggregator,
            registry,
            sample_rate=200,
            export_interval_seconds=0.1,
            export_fn=lambda _time_unix_nano: export_calls.append(1),
        )

        sampler.start()
        try:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not export_calls:
                time.sleep(0.05)
        finally:
            sampler.stop()

        assert export_calls

    def test_start_is_idempotent(self) -> None:
        aggregator = Aggregator()
        registry = ActiveSpanRegistry()
        sampler = Sampler(
            aggregator, registry, 200, 100, export_fn=lambda _time_unix_nano: None
        )

        sampler.start()
        first_thread = sampler._thread  # noqa: SLF001
        sampler.start()

        assert sampler._thread is first_thread  # noqa: SLF001
        sampler.stop()

    def test_does_not_sample_its_own_thread(self) -> None:
        aggregator = Aggregator()
        registry = ActiveSpanRegistry()
        sampler = Sampler(
            aggregator,
            registry,
            sample_rate=200,
            export_interval_seconds=100,
            export_fn=lambda _time_unix_nano: None,
        )

        sampler.start()
        try:
            time.sleep(0.3)
        finally:
            sampler.stop()

        counts = aggregator.drain()
        for stack, _thread_name, _span_id in counts:
            names = [entry[0] for entry in stack]
            assert "_sample_once" not in names
            assert "_run" not in names


@pytest.mark.skipif(
    sys.platform != "linux", reason="/proc-based filtering is Linux-only"
)
class TestOnCpuFiltering:
    def test_busy_thread_is_sampled_much_more_than_blocked_thread(self) -> None:
        aggregator = Aggregator()
        registry = ActiveSpanRegistry()
        sampler = Sampler(
            aggregator,
            registry,
            sample_rate=200,
            export_interval_seconds=100,
            export_fn=lambda _time_unix_nano: None,
        )

        stop_busy = threading.Event()
        stop_blocked = threading.Event()

        def _busy() -> None:
            while not stop_busy.is_set():
                pass

        def _blocked() -> None:
            stop_blocked.wait()

        busy_thread = threading.Thread(target=_busy, name="busy-thread-test")
        blocked_thread = threading.Thread(target=_blocked, name="blocked-thread-test")
        busy_thread.start()
        blocked_thread.start()

        sampler.start()
        try:
            time.sleep(1)
        finally:
            sampler.stop()
            stop_busy.set()
            stop_blocked.set()
            busy_thread.join()
            blocked_thread.join()

        counts = aggregator.drain()
        busy_count = sum(
            count
            for (_stack, name, _span_id), count in counts.items()
            if name == "busy-thread-test"
        )
        blocked_count = sum(
            count
            for (_stack, name, _span_id), count in counts.items()
            if name == "blocked-thread-test"
        )

        min_ratio = 10
        assert busy_count > 0
        assert busy_count >= min_ratio * blocked_count
