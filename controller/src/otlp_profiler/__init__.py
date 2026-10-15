"""In-process continuous CPU profiler that exports the OTLP profiles signal.

Linux-only: on-CPU filtering reads `/proc/<tid>/stat` (see
`linux_thread_state.py`).
"""

import dataclasses
import logging
import threading
from collections.abc import Mapping

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from otlp_profiler.aggregator import Aggregator
from otlp_profiler.exporter import ProfileSettings, ProfileWindow, export
from otlp_profiler.sampler import Sampler
from otlp_profiler.span_registry import ActiveSpanRegistry, SpanLinkingProcessor

logger = logging.getLogger(__name__)

_DEFAULT_SAMPLE_RATE = 100
_DEFAULT_EXPORT_INTERVAL_MS = 500


@dataclasses.dataclass
class _Profiler:
    """The running sampler and the span registry it tags samples from."""

    sampler: Sampler
    span_registry: ActiveSpanRegistry
    span_linking_attached: bool = False


@dataclasses.dataclass
class _State:
    """The process-wide profiler, started by the first `configure()` call."""

    profiler: _Profiler | None = None


_configure_lock = threading.Lock()
_state = _State()


def configure(
    service_name: str,
    endpoint: str,
    sample_rate: int = _DEFAULT_SAMPLE_RATE,
    export_interval_ms: int = _DEFAULT_EXPORT_INTERVAL_MS,
    resource_attributes: Mapping[str, str] | None = None,
) -> None:
    """Start continuous profiling and attach span/profile linking.

    Starts a background sampler that periodically exports OTLP profiles to
    `endpoint`, the full OTLP/HTTP profiles URL, and -- if a real
    `TracerProvider` is the current global tracer provider -- attaches a
    `SpanProcessor` that stamps every span with a `pyroscope.profile.id`
    attribute and tags samples with whichever span is active on their
    thread. The sampler itself is only ever started once.
    If the tracer provider wasn't ready yet on an earlier call, span/profile
    linking is retried on each subsequent call until it succeeds.
    """
    with _configure_lock:
        if _state.profiler is None:
            settings = ProfileSettings(
                service_name, sample_rate, resource_attributes=resource_attributes
            )
            _state.profiler = _start(settings, endpoint, export_interval_ms)
        profiler = _state.profiler

        if profiler.span_linking_attached:
            return

        provider = trace.get_tracer_provider()
        if isinstance(provider, TracerProvider):
            provider.add_span_processor(SpanLinkingProcessor(profiler.span_registry))
            profiler.span_linking_attached = True
        else:
            logger.debug(
                "global TracerProvider not configured, skipping span/profile linking"
            )


def _start(
    settings: ProfileSettings, endpoint: str, export_interval_ms: int
) -> _Profiler:
    aggregator = Aggregator()
    span_registry = ActiveSpanRegistry()

    def _export(time_unix_nano: int) -> None:
        counts = aggregator.drain()
        window = ProfileWindow(time_unix_nano, export_interval_ms * 1_000_000)
        try:
            export(counts, settings, window, endpoint)
        except Exception:
            logger.exception("failed to export profiles")

    sampler = Sampler(
        aggregator,
        span_registry,
        settings.sample_rate,
        export_interval_ms / 1000,
        _export,
    )
    sampler.start()
    return _Profiler(sampler, span_registry)
