#include "camera_metrics.hpp"
#include "sdkconfig.h"

#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED
#include "opentelemetry/metrics/provider.h"
#include "opentelemetry/nostd/shared_ptr.h"

namespace metrics_api = opentelemetry::metrics;

namespace {
static opentelemetry::nostd::shared_ptr<metrics_api::Counter<double>> s_frames_captured;
}
#endif  // CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED

void camera_metrics_setup() {
#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED
    auto meter = metrics_api::Provider::GetMeterProvider()->GetMeter(
        CONFIG_ESP_OPENTELEMETRY_SERVICE_NAME, "1.0.0");
    s_frames_captured = meter->CreateDoubleCounter(
        "dust_mite.frames_captured", "Camera frames captured", "{frame}");
#endif
}

void camera_metrics_update() {
#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED
    if (s_frames_captured) s_frames_captured->Add(1);
#endif
}
