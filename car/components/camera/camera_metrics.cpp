#include "camera_metrics.hpp"
#include "sdkconfig.h"

#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED
#include <cstdint>
#include "metrics.hpp"
#include "opentelemetry/metrics/async_instruments.h"
#include "opentelemetry/metrics/observer_result.h"
#include "opentelemetry/metrics/provider.h"
#include "opentelemetry/nostd/shared_ptr.h"

namespace metrics_api = opentelemetry::metrics;

namespace {

// JPEG frame-buffer capacity the camera driver allocates. Must match the
// camera_config in camera.cpp: FRAMESIZE_VGA (640x480) with the
// CAMERA_JPEG_MODE_FRAME_SIZE_AUTO buffer = width * height / 5.
static constexpr int64_t kFrameBufferBytes = 640 * 480 / 5;  // 61440

static opentelemetry::nostd::shared_ptr<metrics_api::Counter<uint64_t>> s_frames_captured;
static opentelemetry::nostd::shared_ptr<metrics_api::ObservableInstrument> s_frame_size;
static opentelemetry::nostd::shared_ptr<metrics_api::ObservableInstrument> s_frame_buffer;

// Peak delivered frame size since the last metric collection; reset on read so
// each scrape reports the interval peak (the signal for nearing the buffer).
// Written by camera_task, read+reset by the metric-reader thread; a stale or
// lost sample is harmless for this metric, so no atomics/locking needed.
static size_t s_peak_frame_size = 0;

static void cb_frame_size(metrics_api::ObserverResult obs, void*) {
    size_t peak = s_peak_frame_size;
    s_peak_frame_size = 0;
    observe_int64(obs, static_cast<int64_t>(peak));
}
static void cb_frame_buffer(metrics_api::ObserverResult obs, void*) {
    observe_int64(obs, kFrameBufferBytes);
}

}  // namespace
#endif  // CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED

void camera_metrics_setup() {
#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED
    auto meter = metrics_api::Provider::GetMeterProvider()->GetMeter(
        CONFIG_ESP_OPENTELEMETRY_SERVICE_NAME, "1.0.0");

    s_frames_captured = meter->CreateUInt64Counter(
        "dust_mite.frames_captured", "Camera frames captured", "{frame}");

    s_frame_size = meter->CreateInt64ObservableGauge(
        "dust_mite.camera.frame_size_bytes",
        "Peak delivered JPEG frame size since last collection", "By");
    s_frame_size->AddCallback(cb_frame_size, nullptr);

    s_frame_buffer = meter->CreateInt64ObservableGauge(
        "dust_mite.camera.frame_buffer_bytes",
        "JPEG frame-buffer capacity (drop limit)", "By");
    s_frame_buffer->AddCallback(cb_frame_buffer, nullptr);
#endif
}

void camera_metrics_update(size_t frame_size) {
#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED
    if (s_frames_captured) s_frames_captured->Add(1);
    if (frame_size > s_peak_frame_size) s_peak_frame_size = frame_size;
#else
    (void)frame_size;
#endif
}
