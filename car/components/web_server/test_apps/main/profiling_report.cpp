#include "profiling_report.hpp"
#include <cstdio>
#include <memory>
#include "esp_heap_caps.h"
#include "esp_profiling.hpp"

namespace {

// Each export reports how far internal RAM fell since the previous one, a window that holds the
// sampler's aggregation and this export's document build. FreeRTOS objects, lwIP sockets and DMA
// buffers can only use internal RAM, so a profiler that takes it in proportion to the profile
// starves the server it samples.
class InternalRamExporterSpy final : public esp_opentelemetry::ProfilesExporter {
 public:
  InternalRamExporterSpy()
      : window_start_free_(heap_caps_get_free_size(MALLOC_CAP_INTERNAL)) {
    heap_caps_monitor_local_minimum_free_size_start();
  }

  bool Export(const char* /*body*/, std::size_t size) noexcept override {
    const size_t low = heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL);
    heap_caps_monitor_local_minimum_free_size_stop();
    const size_t drop = window_start_free_ > low ? window_start_free_ - low : 0;
    printf("profiles export: %u bytes, internal RAM drop %u bytes\n", static_cast<unsigned>(size),
           static_cast<unsigned>(drop));
    window_start_free_ = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    heap_caps_monitor_local_minimum_free_size_start();
    return true;
  }

 private:
  size_t window_start_free_;
};

}  // namespace

void profiling_report_setup() {
  esp_opentelemetry_profiling_setup(std::make_unique<InternalRamExporterSpy>());
}
