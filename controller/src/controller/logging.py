"""OpenTelemetry logging configuration."""

import logging

from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

logger = logging.getLogger(__name__)


def configure_logging(endpoint: str | None, resource: Resource) -> None:
    """Export the root logger's records over OTLP/HTTP.

    Builds a ``LoggerProvider`` exporting to ``endpoint``, the OTLP base
    endpoint, sets it as the global provider and installs its handler,
    skipping configuration if ``endpoint`` is empty.
    """
    if not endpoint:
        logger.debug("No OTLP endpoint, skipping log configuration")
        return
    exporter = OTLPLogExporter(endpoint=f"{endpoint}/v1/logs")
    provider = LoggerProvider(resource=resource)
    provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    set_logger_provider(provider)
    install_log_handler(provider)


def install_log_handler(provider: LoggerProvider) -> None:
    """Bridge every record reaching the root logger into `provider`."""
    handler = LoggingHandler(
        level=logging.NOTSET,
        logger_provider=provider,
        log_code_attributes=True,
    )
    logging.getLogger().addHandler(handler)
