"""OpenTelemetry logging bridge configuration."""

import logging
import os

from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

from controller.otel import (
    current_repository,
    resolve_current_git_ref,
    resolve_vcs_attributes,
)

logger = logging.getLogger(__name__)


def configure_logging(
    service_name: str, provider: LoggerProvider | None = None
) -> None:
    """Bridge the standard library `logging` module into OpenTelemetry.

    When ``provider`` is omitted, builds a production ``LoggerProvider`` with
    OTLP/HTTP export and sets it as the global provider. Reads
    ``OTEL_EXPORTER_OTLP_ENDPOINT`` (the same endpoint tracing uses, since
    logs route through the OTel Collector like traces) from the environment
    in that case, skipping configuration if it isn't set. Pass a
    ``LoggerProvider`` explicitly to use a custom provider without touching
    the global state (useful in tests).

    Attaches a `LoggingHandler` to the root logger, so every existing
    `logging.getLogger(...)` call site is bridged with no changes to call
    sites or log levels.
    """
    if provider is None:
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if not endpoint:
            logger.debug(
                "OTEL_EXPORTER_OTLP_ENDPOINT not set, skipping log configuration"
            )
            return
        exporter = OTLPLogExporter(endpoint=f"{endpoint}/v1/logs")
        vcs_attributes = resolve_vcs_attributes(
            current_repository(), resolve_current_git_ref()
        )
        resource = Resource.create({SERVICE_NAME: service_name, **vcs_attributes})
        provider = LoggerProvider(resource=resource)
        provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
        set_logger_provider(provider)

    handler = LoggingHandler(level=logging.NOTSET, logger_provider=provider)
    logging.getLogger().addHandler(handler)
