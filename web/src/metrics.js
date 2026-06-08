import { OTLPMetricExporter } from "@opentelemetry/exporter-metrics-otlp-http";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { MeterProvider, PeriodicExportingMetricReader } from "@opentelemetry/sdk-metrics";
import { ATTR_SERVICE_NAME } from "@opentelemetry/semantic-conventions";

let _framesDisplayed;

export function setupMetrics() {
  const provider = new MeterProvider({
    resource: resourceFromAttributes({ [ATTR_SERVICE_NAME]: "dust-mite-web" }),
    readers: [
      new PeriodicExportingMetricReader({
        exporter: new OTLPMetricExporter({
          url: `${import.meta.env.VITE_OTLP_METRICS_ENDPOINT ?? import.meta.env.VITE_OTLP_ENDPOINT ?? "http://localhost:4318"}/v1/metrics`,
        }),
        exportIntervalMillis: 500,
      }),
    ],
  });
  const meter = provider.getMeter("dust-mite-web");
  _framesDisplayed = meter.createCounter("dust_mite.frames_displayed", {
    description: "Browser frames rendered",
    unit: "{frame}",
  });
}

export function recordFrameDisplayed() {
  _framesDisplayed?.add(1);
}
