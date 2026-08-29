import { SeverityNumber, logs } from "@opentelemetry/api-logs";
import { OTLPLogExporter } from "@opentelemetry/exporter-logs-otlp-http";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { BatchLogRecordProcessor, LoggerProvider } from "@opentelemetry/sdk-logs";
import {
  ATTR_EXCEPTION_MESSAGE,
  ATTR_EXCEPTION_STACKTRACE,
  ATTR_EXCEPTION_TYPE,
  ATTR_NETWORK_PROTOCOL_NAME,
  ATTR_SERVICE_NAME,
} from "@opentelemetry/semantic-conventions";

function dropUndefined(attributes) {
  return Object.fromEntries(Object.entries(attributes).filter(([, value]) => value !== undefined));
}

export function setupLogging() {
  const provider = new LoggerProvider({
    resource: resourceFromAttributes({ [ATTR_SERVICE_NAME]: "dust-mite-web" }),
  });
  provider.addLogRecordProcessor(
    new BatchLogRecordProcessor(
      new OTLPLogExporter({
        url: `${import.meta.env.VITE_OTLP_ENDPOINT ?? "http://localhost:4318"}/v1/logs`,
      }),
    ),
  );
  logs.setGlobalLoggerProvider(provider);
  const logger = provider.getLogger("dust-mite-web");

  logger.emit({
    severityNumber: SeverityNumber.DEBUG,
    severityText: "DEBUG",
    body: "dust-mite-web logging initialized",
  });

  return logger;
}

export function buildUncaughtErrorLogRecord({ message, filename, lineno, colno, error }) {
  return {
    severityNumber: SeverityNumber.ERROR,
    severityText: "ERROR",
    body: message || error?.message || "Uncaught error",
    attributes: dropUndefined({
      [ATTR_EXCEPTION_TYPE]: error?.name,
      [ATTR_EXCEPTION_MESSAGE]: error?.message,
      [ATTR_EXCEPTION_STACKTRACE]: error?.stack,
      "code.filepath": filename,
      "code.lineno": lineno,
      "code.colno": colno,
    }),
  };
}

export function buildWsAbnormalCloseLogRecord({ url, code, reason, wasClean }) {
  return {
    severityNumber: SeverityNumber.ERROR,
    severityText: "ERROR",
    body: `WebSocket closed abnormally: code=${code}${reason ? `, reason=${reason}` : ""}`,
    attributes: dropUndefined({
      "ws.url": url,
      [ATTR_NETWORK_PROTOCOL_NAME]: "websocket",
      "ws.close.code": code,
      "ws.close.reason": reason || undefined,
      "ws.close.wasClean": wasClean,
    }),
  };
}
