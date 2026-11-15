"""OpenTelemetry logging configuration."""

import logging

from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

logger = logging.getLogger(__name__)


def configure_logging(endpoint: str | None, resource: Resource) -> logging.Handler:
    """Send `controller` records from DEBUG to the console and any OTLP `endpoint`.

    Returns the console handler.
    """
    logging.getLogger(__package__).setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(logging.BASIC_FORMAT))
    logging.getLogger().addHandler(console_handler)
    if not endpoint:
        logger.debug("No OTLP logs endpoint, skipping log configuration")
        return console_handler
    exporter = OTLPLogExporter(endpoint=endpoint)
    provider = LoggerProvider(resource=resource)
    provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    set_logger_provider(provider)
    install_log_handler(provider)
    return console_handler


def install_log_handler(provider: LoggerProvider) -> None:
    """Bridge every record reaching the root logger into `provider`."""
    handler = LoggingHandler(
        level=logging.NOTSET,
        logger_provider=provider,
        log_code_attributes=True,
    )
    logging.getLogger().addHandler(handler)
