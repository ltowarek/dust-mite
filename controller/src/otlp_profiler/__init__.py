"""In-process continuous CPU profiler that exports the OTLP profiles signal.

Linux-only: on-CPU filtering reads `/proc/<tid>/stat` (see
`linux_thread_state.py`).
"""

import logging
import threading
from collections.abc import Mapping

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from otlp_profiler.aggregator import Aggregator
from otlp_profiler.exporter import export
from otlp_profiler.sampler import Sampler
from otlp_profiler.span_registry import ActiveSpanRegistry, SpanLinkingProcessor

logger = logging.getLogger(__name__)

_DEFAULT_SAMPLE_RATE = 100
_DEFAULT_EXPORT_INTERVAL_MS = 500


_configure_lock = threading.Lock()
_sampler: Sampler | None = None
_span_registry: ActiveSpanRegistry | None = None
_span_linking_attached = False


def configure(
    service_name: str,
    endpoint: str,
    sample_rate: int = _DEFAULT_SAMPLE_RATE,
    export_interval_ms: int = _DEFAULT_EXPORT_INTERVAL_MS,
    resource_attributes: Mapping[str, str] | None = None,
) -> None:
    """Start continuous profiling and attach span/profile linking.

    Starts a background sampler that periodically exports OTLP profiles to
    `endpoint`, and -- if a real `TracerProvider` is the current global
    tracer provider -- attaches a `SpanProcessor` that stamps every span with
    a `pyroscope.profile.id` attribute and tags samples with whichever span
    is active on their thread. The sampler itself is only ever started once.
    If the tracer provider wasn't ready yet on an earlier call, span/profile
    linking is retried on each subsequent call until it succeeds.
    """
    # Guarded by _configure_lock, so this is a lazy singleton, not implicit
    # shared mutable state -- the pattern PLW0603 otherwise warns about.
    global _sampler, _span_registry, _span_linking_attached  # noqa: PLW0603
    with _configure_lock:
        if _sampler is None:
            aggregator = Aggregator()
            _span_registry = ActiveSpanRegistry()
            export_interval_seconds = export_interval_ms / 1000

            def _export(time_unix_nano: int) -> None:
                counts = aggregator.drain()
                duration_nano = export_interval_ms * 1_000_000
                try:
                    export(
                        counts,
                        service_name,
                        endpoint,
                        sample_rate,
                        time_unix_nano,
                        duration_nano,
                        resource_attributes=resource_attributes,
                    )
                except Exception:
                    logger.exception("failed to export profiles")

            _sampler = Sampler(
                aggregator,
                _span_registry,
                sample_rate,
                export_interval_seconds,
                _export,
            )
            _sampler.start()

        if _span_linking_attached:
            return

        provider = trace.get_tracer_provider()
        if isinstance(provider, TracerProvider):
            assert _span_registry is not None
            provider.add_span_processor(SpanLinkingProcessor(_span_registry))
            _span_linking_attached = True
        else:
            logger.debug(
                "global TracerProvider not configured, skipping span/profile linking"
            )
