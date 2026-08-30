import inspect
import logging
from collections.abc import Generator

import pytest
from opentelemetry import trace
from opentelemetry._logs import SeverityNumber
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    InMemoryLogRecordExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from controller.logging import configure_logging


def _make_tracer_provider() -> TracerProvider:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider


@pytest.fixture
def exporter() -> Generator[InMemoryLogRecordExporter, None, None]:
    log_exporter = InMemoryLogRecordExporter()  # type: ignore[no-untyped-call]
    log_provider = LoggerProvider()
    log_provider.add_log_record_processor(SimpleLogRecordProcessor(log_exporter))
    root_handlers = list(logging.getLogger().handlers)

    configure_logging("test-service", provider=log_provider)

    yield log_exporter

    logging.getLogger().handlers = root_handlers


def test_bridges_severity_and_body(exporter: InMemoryLogRecordExporter) -> None:
    test_logger = logging.getLogger("test-bridges-severity-and-body")
    test_logger.setLevel(logging.DEBUG)

    test_logger.warning("Something happened: %s", "boom")

    records = exporter.get_finished_logs()
    assert len(records) == 1
    record = records[0].log_record
    assert record.body == "Something happened: boom"
    assert record.severity_text == "WARN"
    assert record.severity_number == SeverityNumber.WARN


def test_bridges_debug_level(exporter: InMemoryLogRecordExporter) -> None:
    """Nothing filters DEBUG out -- both entry points already run at DEBUG."""
    test_logger = logging.getLogger("test-bridges-debug-level")
    test_logger.setLevel(logging.DEBUG)

    test_logger.debug("Verbose detail")

    records = exporter.get_finished_logs()
    assert len(records) == 1
    assert records[0].log_record.severity_text == "DEBUG"


def test_correlates_with_active_span(exporter: InMemoryLogRecordExporter) -> None:
    trace.set_tracer_provider(_make_tracer_provider())
    tracer = trace.get_tracer(__name__)
    test_logger = logging.getLogger("test-correlates-with-active-span")
    test_logger.setLevel(logging.DEBUG)

    with tracer.start_as_current_span("test-span") as span:
        span_context = span.get_span_context()
        test_logger.info("Inside span")

    records = exporter.get_finished_logs()
    assert len(records) == 1
    record = records[0].log_record
    assert record.trace_id == span_context.trace_id
    assert record.span_id == span_context.span_id


def test_no_correlation_without_active_span(
    exporter: InMemoryLogRecordExporter,
) -> None:
    test_logger = logging.getLogger("test-no-correlation-without-active-span")
    test_logger.setLevel(logging.DEBUG)

    test_logger.info("No span here")

    records = exporter.get_finished_logs()
    assert len(records) == 1
    record = records[0].log_record
    assert record.trace_id == 0
    assert record.span_id == 0


def test_records_carry_source_location(exporter: InMemoryLogRecordExporter) -> None:
    """Records carry the call site, not just the message text."""
    test_logger = logging.getLogger("test-records-carry-source-location")
    test_logger.setLevel(logging.DEBUG)

    test_logger.info("Locate me")
    expected_line = inspect.currentframe().f_lineno - 1  # type: ignore[union-attr]

    records = exporter.get_finished_logs()
    assert len(records) == 1
    attributes = records[0].log_record.attributes or {}
    assert attributes["code.file.path"] == __file__
    assert attributes["code.line.number"] == expected_line
