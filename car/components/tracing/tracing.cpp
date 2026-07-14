#include "tracing.hpp"

#include "opentelemetry/context/runtime_context.h"
#include "opentelemetry/context/propagation/global_propagator.h"
#include "opentelemetry/trace/propagation/http_trace_context.h"

#include <string>

namespace {

class CJsonCarrier : public opentelemetry::context::propagation::TextMapCarrier {
 public:
  explicit CJsonCarrier(cJSON& obj) : obj_(obj) {}

  [[nodiscard]] opentelemetry::nostd::string_view Get(
      opentelemetry::nostd::string_view key) const noexcept override {
    std::string k(key.data(), key.size());
    const cJSON* item = cJSON_GetObjectItemCaseSensitive(&obj_, k.c_str());
    if (item == nullptr || !cJSON_IsString(item) || item->valuestring == nullptr) {
      return {};
    }
    return {item->valuestring};
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

void tracing_inject(cJSON& obj) {
  auto propagator =
      opentelemetry::context::propagation::GlobalTextMapPropagator::GetGlobalPropagator();
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
      opentelemetry::context::propagation::GlobalTextMapPropagator::GetGlobalPropagator();
  if (!propagator) {
    return current;
  }
  // cJSON APIs do not take const - the carrier only reads, but we need a
  // non-const reference for cJSON_GetObjectItemCaseSensitive.
  CJsonCarrier carrier(const_cast<cJSON&>(obj));
  return propagator->Extract(carrier, current);
}
