import { SpanKind, SpanStatusCode, context, trace } from "@opentelemetry/api";
import { W3CTraceContextPropagator } from "@opentelemetry/core";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { SimpleSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { WebTracerProvider } from "@opentelemetry/sdk-trace-web";
import { ATTR_SERVICE_NAME } from "@opentelemetry/semantic-conventions";
import { DriveController, driveStatusText } from "./drive.js";
import {
  buildUncaughtErrorLogRecord,
  buildWsAbnormalCloseLogRecord,
  setupLogging,
} from "./logging.js";
import { handleMessage } from "./messages.js";

const provider = new WebTracerProvider({
  resource: resourceFromAttributes({ [ATTR_SERVICE_NAME]: "dust-mite-web" }),
  spanProcessors: [
    new SimpleSpanProcessor(
      new OTLPTraceExporter({
        url: `${import.meta.env.VITE_OTLP_ENDPOINT ?? "http://localhost:4318"}/v1/traces`,
      }),
    ),
  ],
});
provider.register({ propagator: new W3CTraceContextPropagator() });
const tracer = provider.getTracer("dust-mite-web");

const logger = setupLogging();

window.addEventListener("error", (event) => {
  logger.emit(
    buildUncaughtErrorLogRecord({
      message: event.message,
      filename: event.filename,
      lineno: event.lineno,
      colno: event.colno,
      error: event.error,
    }),
  );
});

function openStreamerSocket(url, elements) {
  const socket = new WebSocket(url);

  let connectionSpan = null;
  let connectionContext = null;

  socket.addEventListener("open", () => {
    connectionSpan = tracer.startSpan("ws.connection", {
      kind: SpanKind.CLIENT,
      attributes: {
        "ws.url": socket.url,
        "network.protocol.name": "websocket",
      },
    });
    connectionContext = trace.setSpan(context.active(), connectionSpan);
  });

  socket.addEventListener("message", (event) => {
    handleMessage(JSON.parse(event.data), elements);
  });

  socket.addEventListener("close", (event) => {
    if (event.code !== 1000 || !event.wasClean) {
      logger.emit({
        ...buildWsAbnormalCloseLogRecord({
          url: socket.url,
          code: event.code,
          reason: event.reason,
          wasClean: event.wasClean,
        }),
        context: connectionContext ?? undefined,
      });
    }

    if (connectionSpan) {
      connectionSpan.setAttribute("ws.close.code", event.code);
      connectionSpan.end();
    }
  });

  socket.addEventListener("error", () => {
    if (connectionSpan) {
      connectionSpan.setStatus({
        code: SpanStatusCode.ERROR,
        message: "WebSocket error",
      });
      connectionSpan.end();
    }
  });

  return socket;
}

window.addEventListener("DOMContentLoaded", () => {
  const streamerUrl = import.meta.env.VITE_WS_URL ?? "ws://localhost:8765";
  const cameraUrl = import.meta.env.VITE_CAMERA_URL ?? "http://localhost:8766/camera";

  document.getElementById("image").src = cameraUrl;

  const elements = {
    timestamp: document.getElementById("timestamp"),
    rssi: document.getElementById("rssi"),
    speed: document.getElementById("speed"),
    accelerometer: document.getElementById("accelerometer"),
    magnetometer: document.getElementById("magnetometer"),
    gyroscope: document.getElementById("gyroscope"),
    distance_ahead: document.getElementById("distance_ahead"),
    collision_monitor: document.getElementById("collision_monitor"),
  };

  openStreamerSocket(`${streamerUrl}/telemetry`, elements);

  const driveSocket = openStreamerSocket(`${streamerUrl}/drive`, elements);
  const driveController = new DriveController(driveSocket);
  driveController.start();
  driveSocket.addEventListener("close", (event) => {
    driveController.stop();
    document.getElementById("drive_status").innerText = driveStatusText(event);
  });
});
