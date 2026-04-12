import { SpanKind, SpanStatusCode, context, propagation, trace } from "https://esm.sh/@opentelemetry/api@1";
import { W3CTraceContextPropagator } from "https://esm.sh/@opentelemetry/core@1";
import { SimpleSpanProcessor } from "https://esm.sh/@opentelemetry/sdk-trace-base@1";
import { WebTracerProvider } from "https://esm.sh/@opentelemetry/sdk-trace-web@1";
import { Resource } from "https://esm.sh/@opentelemetry/resources@1";
import { ATTR_SERVICE_NAME } from "https://esm.sh/@opentelemetry/semantic-conventions@1";

// TODO: Remove this custom exporter and use OTLP exporter from OpenTelemetry JS - bundler is needed
class FetchOTLPExporter {
  constructor(url) {
    this._url = url;
  }

  export(spans, resultCallback) {
    const body = {
      resourceSpans: spans.map((span) => ({
        resource: {
          attributes: this._toOTLPAttributes(span.resource.attributes),
        },
        scopeSpans: [
          {
            scope: { name: span.instrumentationLibrary.name },
            spans: [
              {
                traceId: span.spanContext().traceId,
                spanId: span.spanContext().spanId,
                parentSpanId: span.parentSpanId,
                name: span.name,
                kind: span.kind + 1,
                startTimeUnixNano: String(
                  span.startTime[0] * 1e9 + span.startTime[1],
                ),
                endTimeUnixNano: String(
                  span.endTime[0] * 1e9 + span.endTime[1],
                ),
                attributes: this._toOTLPAttributes(span.attributes),
                status: { code: span.status.code },
                events: [],
                links: [],
              },
            ],
          },
        ],
      })),
    };

    fetch(this._url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(() => resultCallback({ code: 0 }))
      .catch((err) => {
        console.error("[tracing] Export failed:", err);
        resultCallback({ code: 1 });
      });
  }

  _toOTLPAttributes(attrs) {
    return Object.entries(attrs).map(([key, value]) => ({
      key,
      value: this._toOTLPValue(value),
    }));
  }

  _toOTLPValue(value) {
    if (typeof value === "string") return { stringValue: value };
    if (typeof value === "boolean") return { boolValue: value };
    if (typeof value === "number") {
      return Number.isInteger(value)
        ? { intValue: String(value) }
        : { doubleValue: value };
    }
    return { stringValue: String(value) };
  }

  shutdown() {
    return Promise.resolve();
  }
}

const provider = new WebTracerProvider({
  resource: new Resource({ [ATTR_SERVICE_NAME]: "dust-mite-web" }),
  spanProcessors: [
    new SimpleSpanProcessor(new FetchOTLPExporter("http://localhost:4318/v1/traces")),
  ],
});
provider.register({ propagator: new W3CTraceContextPropagator() });
const tracer = provider.getTracer("dust-mite-web");

window.addEventListener("DOMContentLoaded", () => {
  const socket = new WebSocket("ws://localhost:8765");

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
    const extractedContext = propagation.extract(
      connectionContext ?? context.active(),
      carrier,
    );

    const messageSpan = tracer.startSpan(
      `ws.message.receive.${event_data["type"]}`,
      {
        kind: SpanKind.CLIENT,
        attributes: {
          "ws.message.type": event_data["type"],
          "ws.message.size": event.data.length,
        },
      },
      extractedContext,
    );

    try {
      if (event_data["type"] == "stream") {
        image.src = "data:image/jpeg;base64," + event_data["data"];
      } else if (event_data["type"] == "telemetry") {
        const data = event_data["data"];

        timestamp.innerText = data.timestamp;
        rssi.innerText = `${data.rssi} dBm`;
        speed.innerText = `${data.speed.toFixed(2)} km/h`;

        const a = data.accelerometer;
        const m = data.magnetometer;
        const g = data.gyroscope;
        accelerometer.innerText = `${a.x.toFixed(2)}, ${a.y.toFixed(2)}, ${a.z.toFixed(2)} g`;
        magnetometer.innerText = `${m.x.toFixed(2)}, ${m.y.toFixed(2)}, ${m.z.toFixed(2)} G`;
        gyroscope.innerText = `${g.x.toFixed(2)}, ${g.y.toFixed(2)}, ${g.z.toFixed(2)} degrees/s`;

        distance_ahead.innerText = `${data.distance_ahead} cm`;
      }
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

  const image = document.getElementById("image");
  const timestamp = document.getElementById("timestamp");
  const rssi = document.getElementById("rssi");
  const speed = document.getElementById("speed");
  const accelerometer = document.getElementById("accelerometer");
  const magnetometer = document.getElementById("magnetometer");
  const gyroscope = document.getElementById("gyroscope");
  const distance_ahead = document.getElementById("distance_ahead");
});
