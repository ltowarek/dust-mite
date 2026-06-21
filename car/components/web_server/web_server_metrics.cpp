#include "web_server_metrics.hpp"
#include "sdkconfig.h"

#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED
#include <cstdint>
#include "opentelemetry/metrics/provider.h"
#include "opentelemetry/nostd/shared_ptr.h"

namespace metrics_api = opentelemetry::metrics;

namespace {
static opentelemetry::nostd::shared_ptr<metrics_api::Counter<uint64_t>> s_frames_sent;
}
#endif  // CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED

void web_server_metrics_setup() {
#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED
    auto meter = metrics_api::Provider::GetMeterProvider()->GetMeter(
        CONFIG_ESP_OPENTELEMETRY_SERVICE_NAME, "1.0.0");
    s_frames_sent = meter->CreateUInt64Counter(
        "dust_mite.frames_sent", "Camera frames sent to client", "{frame}");
#endif
}

void web_server_metrics_update() {
#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED
    if (s_frames_sent) s_frames_sent->Add(1);
#endif
}
