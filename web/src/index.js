import { SpanKind, SpanStatusCode, context, propagation, trace } from "@opentelemetry/api";
import { W3CTraceContextPropagator } from "@opentelemetry/core";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { SimpleSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { WebTracerProvider } from "@opentelemetry/sdk-trace-web";
import { ATTR_SERVICE_NAME } from "@opentelemetry/semantic-conventions";
import { handleMessage } from "./messages.js";

const provider = new WebTracerProvider({
  resource: resourceFromAttributes({ [ATTR_SERVICE_NAME]: "dust-mite-web" }),
  spanProcessors: [
    new SimpleSpanProcessor(new OTLPTraceExporter({ url: "http://localhost:4318/v1/traces" })),
  ],
});
provider.register({ propagator: new W3CTraceContextPropagator() });
const tracer = provider.getTracer("dust-mite-web");

window.addEventListener("DOMContentLoaded", () => {
  const socket = new WebSocket("ws://localhost:8765");

  const elements = {
    image: document.getElementById("image"),
    timestamp: document.getElementById("timestamp"),
    rssi: document.getElementById("rssi"),
    speed: document.getElementById("speed"),
    accelerometer: document.getElementById("accelerometer"),
    magnetometer: document.getElementById("magnetometer"),
    gyroscope: document.getElementById("gyroscope"),
    distance_ahead: document.getElementById("distance_ahead"),
  };

  let connectionSpan = null;
  let connectionContext = null;

  socket.onopen = () => {
    connectionSpan = tracer.startSpan("ws.connection", {
      kind: SpanKind.CLIENT,
      attributes: {
        "ws.url": socket.url,
        "network.protocol.name": "websocket",
      },
    });
    connectionContext = trace.setSpan(context.active(), connectionSpan);
  };

  socket.onmessage = (event) => {
    const event_data = JSON.parse(event.data);

    const carrier = {
      traceparent: event_data.traceparent,
      tracestate: event_data.tracestate,
    };
    const extractedContext = propagation.extract(connectionContext ?? context.active(), carrier);

    const messageSpan = tracer.startSpan(
      `ws.message.receive.${event_data.type}`,
      {
        kind: SpanKind.CLIENT,
        attributes: {
          "ws.message.type": event_data.type,
          "ws.message.size": event.data.length,
        },
      },
      extractedContext,
    );

    try {
      handleMessage(event_data, elements);
    } finally {
      messageSpan.end();
    }
  };

  socket.onclose = (event) => {
    if (connectionSpan) {
      connectionSpan.setAttribute("ws.close.code", event.code);
      connectionSpan.end();
    }
  };

  socket.onerror = () => {
    if (connectionSpan) {
      connectionSpan.setStatus({
        code: SpanStatusCode.ERROR,
        message: "WebSocket error",
      });
      connectionSpan.end();
    }
  };
});
