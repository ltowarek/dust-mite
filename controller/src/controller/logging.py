"""OpenTelemetry logging configuration."""

import logging

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
    service_name: str, endpoint: str | None, provider: LoggerProvider | None = None
) -> None:
    """Configure OpenTelemetry logging for `service_name`.

    When ``provider`` is omitted, builds a production ``LoggerProvider`` with
    OTLP/HTTP export to ``endpoint``, the OTLP base endpoint
    (``OTEL_EXPORTER_OTLP_ENDPOINT``), and sets it as the global provider,
    skipping configuration if ``endpoint`` is empty. Pass a ``LoggerProvider``
    explicitly to use a custom provider without touching the global state
    (useful in tests).
    """
    if provider is None:
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

    handler = LoggingHandler(
        level=logging.NOTSET,
        logger_provider=provider,
        log_code_attributes=True,
    )
    logging.getLogger().addHandler(handler)
