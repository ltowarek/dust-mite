"""In-process continuous CPU profiler that exports the OTLP profiles signal.

Linux-only: on-CPU filtering reads `/proc/<tid>/stat` (see
`linux_thread_state.py`).
"""

import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

from otlp_profiler.aggregator import Aggregator
from otlp_profiler.exporter import ProfileSettings, ProfileWindow, export
from otlp_profiler.sampler import Sampler
from otlp_profiler.span_registry import ActiveSpanRegistry, SpanLinkingProcessor

logger = logging.getLogger(__name__)

_DEFAULT_SAMPLE_RATE = 100
_DEFAULT_EXPORT_INTERVAL_MS = 500


def configure(
    endpoint: str,
    resource: Resource,
    sample_rate: int = _DEFAULT_SAMPLE_RATE,
    export_interval_ms: int = _DEFAULT_EXPORT_INTERVAL_MS,
) -> None:
    """Start continuous profiling and attach span/profile linking.

    Starts a background sampler that periodically exports OTLP profiles of
    `resource` to `endpoint`, the full OTLP/HTTP profiles URL, and -- if a real
    `TracerProvider` is the current global tracer provider -- attaches a
    `SpanProcessor` that stamps every span with a `pyroscope.profile.id`
    attribute and tags samples with whichever span is active on their
    thread. Call it once per process, after the global tracer provider is
    set, as with the other signals' configure functions.
    """
    aggregator = Aggregator()
    span_registry = ActiveSpanRegistry()
    settings = ProfileSettings(resource, sample_rate)

    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.add_span_processor(SpanLinkingProcessor(span_registry))
    else:
        logger.debug(
            "global TracerProvider not configured, skipping span/profile linking"
        )

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
        sample_rate,
        export_interval_ms / 1000,
        _export,
    )
    sampler.start()
