#include "tracing.hpp"

#include "opentelemetry/context/runtime_context.h"
#include "opentelemetry/context/propagation/global_propagator.h"
#include "opentelemetry/trace/propagation/http_trace_context.h"

#include <string>

namespace {

class CJsonCarrier : public opentelemetry::context::propagation::TextMapCarrier {
 public:
  explicit CJsonCarrier(cJSON* obj) : obj_(obj) {}

  [[nodiscard]] opentelemetry::nostd::string_view Get(
      opentelemetry::nostd::string_view key) const noexcept override {
    std::string k(key.data(), key.size());
    const cJSON* item = cJSON_GetObjectItemCaseSensitive(obj_, k.c_str());
    if (item == nullptr || !cJSON_IsString(item) || item->valuestring == nullptr) {
      return {};
    }
    return {item->valuestring};
  }

  void Set(opentelemetry::nostd::string_view /*key*/,
           opentelemetry::nostd::string_view /*value*/) noexcept override {}

 private:
  cJSON* obj_;
};

class HeadersCarrier : public opentelemetry::context::propagation::TextMapCarrier {
 public:
  explicit HeadersCarrier(trace_headers_t& headers) : headers_(headers) {}

  [[nodiscard]] opentelemetry::nostd::string_view Get(
      opentelemetry::nostd::string_view /*key*/) const noexcept override {
    return {};
  }

  void Set(opentelemetry::nostd::string_view key,
           opentelemetry::nostd::string_view value) noexcept override {
    if (key == "traceparent") {
      headers_.traceparent.assign(value.data(), value.size());
    } else if (key == "tracestate") {
      headers_.tracestate.assign(value.data(), value.size());
    }
  }

 private:
  trace_headers_t& headers_;
};

}  // namespace

trace_headers_t tracing_headers() {
  trace_headers_t headers;
  auto propagator =
      opentelemetry::context::propagation::GlobalTextMapPropagator::GetGlobalPropagator();
  if (!propagator) {
    return headers;
  }
  HeadersCarrier carrier(headers);
  propagator->Inject(carrier, opentelemetry::context::RuntimeContext::GetCurrent());
  return headers;
}

static void set_string(cJSON* obj, const char* key, const std::string& value) {
  if (value.empty()) {
    return;
  }
  cJSON_DeleteItemFromObjectCaseSensitive(obj, key);
  cJSON_AddStringToObject(obj, key, value.c_str());
}

void tracing_inject(cJSON* obj) {
  trace_headers_t headers = tracing_headers();
  set_string(obj, "traceparent", headers.traceparent);
  set_string(obj, "tracestate", headers.tracestate);
}

opentelemetry::context::Context tracing_extract(const cJSON* obj) {
  auto current = opentelemetry::context::RuntimeContext::GetCurrent();
  auto propagator =
      opentelemetry::context::propagation::GlobalTextMapPropagator::GetGlobalPropagator();
  if (!propagator) {
    return current;
  }
  // The carrier only reads here, but it also implements Set, so it holds a non-const pointer.
  CJsonCarrier carrier(const_cast<cJSON*>(obj));
  return propagator->Extract(carrier, current);
}
