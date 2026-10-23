#include "metrics_collection.hpp"

#include <chrono>
#include <memory>

#include "camera_metrics.hpp"
#include "esp_metrics.hpp"
#include "opentelemetry/sdk/common/exporter_utils.h"
#include "opentelemetry/sdk/metrics/push_metric_exporter.h"
#include "sdkconfig.h"
#include "system_metrics.hpp"
#include "telemetry_metrics.hpp"

namespace {

namespace sdk_metrics = opentelemetry::sdk::metrics;

class MetricExporterStub final : public sdk_metrics::PushMetricExporter {
 public:
  opentelemetry::sdk::common::ExportResult Export(
      const sdk_metrics::ResourceMetrics& /*data*/) noexcept override {
    return opentelemetry::sdk::common::ExportResult::kSuccess;
  }

  sdk_metrics::AggregationTemporality GetAggregationTemporality(
      sdk_metrics::InstrumentType /*instrument_type*/) const noexcept override {
    return sdk_metrics::AggregationTemporality::kCumulative;
  }

  bool ForceFlush(std::chrono::microseconds /*timeout*/) noexcept override { return true; }

  bool Shutdown(std::chrono::microseconds /*timeout*/) noexcept override { return true; }
};

}  // namespace

void metrics_collection_setup() {
  esp_opentelemetry_metrics_setup(std::make_unique<MetricExporterStub>(),
                                  {{"service.name", CONFIG_ESP_OPENTELEMETRY_SERVICE_NAME}});
  system_metrics_setup();
  telemetry_metrics_setup();
  camera_metrics_setup();
}
