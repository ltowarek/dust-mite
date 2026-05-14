#include "tracing.hpp"
#include "esp_pthread.h"
#include "esp_heap_caps.h"
#include "sdkconfig.h"

#include "opentelemetry/context/runtime_context.h"
#include "opentelemetry/context/propagation/global_propagator.h"
#include "opentelemetry/trace/propagation/http_trace_context.h"

#include <string>

namespace {

class CJsonCarrier
    : public opentelemetry::context::propagation::TextMapCarrier {
public:
  explicit CJsonCarrier(cJSON& obj) : obj_(obj) {}

  opentelemetry::nostd::string_view Get(
      opentelemetry::nostd::string_view key) const noexcept override {
    std::string k(key.data(), key.size());
    const cJSON* item = cJSON_GetObjectItemCaseSensitive(&obj_, k.c_str());
    if (item == nullptr || !cJSON_IsString(item) ||
        item->valuestring == nullptr) {
      return {};
    }
    return opentelemetry::nostd::string_view(item->valuestring);
  }

  void Set(opentelemetry::nostd::string_view key,
           opentelemetry::nostd::string_view value) noexcept override {
    std::string k(key.data(), key.size());
    std::string v(value.data(), value.size());
    cJSON_DeleteItemFromObjectCaseSensitive(&obj_, k.c_str());
    cJSON_AddStringToObject(&obj_, k.c_str(), v.c_str());
  }

private:
  cJSON& obj_;
};

}  // namespace

void tracing_setup() {
#ifdef CONFIG_ESP_OPENTELEMETRY_TRACING_ENABLED
  // Route BatchSpanProcessor pthread stack to PSRAM to avoid DRAM exhaustion.
  esp_pthread_cfg_t cfg = esp_pthread_get_default_config();
  cfg.stack_alloc_caps = MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT;
  esp_pthread_set_cfg(&cfg);
#endif

  esp_opentelemetry_setup(CONFIG_ESP_OPENTELEMETRY_SERVICE_NAME);

#ifdef CONFIG_ESP_OPENTELEMETRY_TRACING_ENABLED
  esp_pthread_cfg_t default_cfg = esp_pthread_get_default_config();
  esp_pthread_set_cfg(&default_cfg);
#endif
}

void tracing_inject(cJSON& obj) {
  auto propagator =
      opentelemetry::context::propagation::GlobalTextMapPropagator::
          GetGlobalPropagator();
  if (!propagator) {
    return;
  }
  CJsonCarrier carrier(obj);
  auto ctx = opentelemetry::context::RuntimeContext::GetCurrent();
  propagator->Inject(carrier, ctx);
}

opentelemetry::context::Context tracing_extract(const cJSON& obj) {
  auto current = opentelemetry::context::RuntimeContext::GetCurrent();
  auto propagator =
      opentelemetry::context::propagation::GlobalTextMapPropagator::
          GetGlobalPropagator();
  if (!propagator) {
    return current;
  }
  // cJSON APIs do not take const - the carrier only reads, but we need a
  // non-const reference for cJSON_GetObjectItemCaseSensitive.
  CJsonCarrier carrier(const_cast<cJSON&>(obj));
  return propagator->Extract(carrier, current);
}
