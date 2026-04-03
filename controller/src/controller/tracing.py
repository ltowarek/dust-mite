"""OpenTelemetry tracer configuration."""

import logging
import os
from typing import Any

from opentelemetry import context, propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

logger = logging.getLogger(__name__)


def inject_trace_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``payload`` with the active trace context added.

    Embeds the current span's W3C traceparent (and optionally
    tracestate) into the dict so a WebSocket receiver can extract and
    continue the trace.
    """
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return {**payload, **carrier}


def extract_trace_context(payload: dict[str, Any]) -> context.Context:
    """Extract and return the trace context from a WebSocket payload.

    Reads W3C traceparent (and optionally tracestate) from the dict so
    the receiver can continue the trace started by the sender.
    """
    return propagate.extract(payload)


def configure_tracing(service_name: str) -> None:
    """Configure global OpenTelemetry tracer with OTLP/HTTP export.

    Sets the global TracerProvider and W3C TraceContext TextMapPropagator.
    Call once at application startup before any spans are created.

    The OTLP endpoint is read from the ``OTEL_EXPORTER_OTLP_ENDPOINT``
    environment variable.
    """
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.debug(
            "OTEL_EXPORTER_OTLP_ENDPOINT not set, skipping tracer configuration"
        )
        return
    exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    set_global_textmap(TraceContextTextMapPropagator())
