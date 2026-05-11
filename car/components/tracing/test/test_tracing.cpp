#include "tracing.hpp"
#include "unity.h"
#include <cJSON.h>
#include <cstring>

#include "opentelemetry/context/propagation/global_propagator.h"
#include "opentelemetry/context/runtime_context.h"
#include "opentelemetry/trace/context.h"
#include "opentelemetry/trace/default_span.h"
#include "opentelemetry/trace/propagation/http_trace_context.h"
#include "opentelemetry/trace/span_context.h"
#include "opentelemetry/trace/trace_flags.h"

const char traceparent[] =
    "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";

// void setUp() {
//     namespace prop = opentelemetry::context::propagation;
//     prop::GlobalTextMapPropagator::SetGlobalPropagator(
//         opentelemetry::nostd::shared_ptr<prop::TextMapPropagator>(
//             new opentelemetry::trace::propagation::HttpTraceContext()));
// }

// void tearDown() {
//     namespace prop = opentelemetry::context::propagation;
//     prop::GlobalTextMapPropagator::SetGlobalPropagator(
//         opentelemetry::nostd::shared_ptr<prop::TextMapPropagator>(nullptr));
// }

TEST_CASE("extract valid traceparent", "[tracing]") {
    cJSON *obj = cJSON_CreateObject();
    cJSON_AddStringToObject(obj, "traceparent", traceparent);

    opentelemetry::context::Context ctx = tracing_extract(*obj);
    cJSON_Delete(obj);

    opentelemetry::nostd::shared_ptr<opentelemetry::trace::Span> span =
        opentelemetry::trace::GetSpan(ctx);
    opentelemetry::trace::SpanContext sc = span->GetContext();

    TEST_ASSERT_TRUE(sc.IsValid());

    char trace_buf[33] = {};
    sc.trace_id().ToLowerBase16({trace_buf, 32});
    TEST_ASSERT_EQUAL_STRING("4bf92f3577b34da6a3ce929d0e0e4736", trace_buf);

    char span_buf[17] = {};
    sc.span_id().ToLowerBase16({span_buf, 16});
    TEST_ASSERT_EQUAL_STRING("00f067aa0ba902b7", span_buf);

    TEST_ASSERT_TRUE(sc.trace_flags().IsSampled());
}

TEST_CASE("extract missing traceparent key", "[tracing]") {
    cJSON *obj = cJSON_CreateObject();

    opentelemetry::context::Context ctx = tracing_extract(*obj);
    cJSON_Delete(obj);

    opentelemetry::trace::SpanContext sc =
        opentelemetry::trace::GetSpan(ctx)->GetContext();
    TEST_ASSERT_FALSE(sc.IsValid());
}

TEST_CASE("extract null traceparent value", "[tracing]") {
    cJSON *obj = cJSON_CreateObject();
    cJSON_AddNullToObject(obj, "traceparent");

    opentelemetry::context::Context ctx = tracing_extract(*obj);
    cJSON_Delete(obj);

    opentelemetry::trace::SpanContext sc =
        opentelemetry::trace::GetSpan(ctx)->GetContext();
    TEST_ASSERT_FALSE(sc.IsValid());
}

TEST_CASE("extract non-string traceparent value", "[tracing]") {
    cJSON *obj = cJSON_CreateObject();
    cJSON_AddNumberToObject(obj, "traceparent", 42);

    opentelemetry::context::Context ctx = tracing_extract(*obj);
    cJSON_Delete(obj);

    opentelemetry::trace::SpanContext sc =
        opentelemetry::trace::GetSpan(ctx)->GetContext();
    TEST_ASSERT_FALSE(sc.IsValid());
}

TEST_CASE("inject with no active span", "[tracing]") {
    cJSON *obj = cJSON_CreateObject();
    tracing_inject(*obj);

    const cJSON *tp = cJSON_GetObjectItemCaseSensitive(obj, "traceparent");
    cJSON_Delete(obj);

    TEST_ASSERT_NULL(tp);
}

TEST_CASE("inject with valid span", "[tracing]") {
    const uint8_t trace_bytes[16] = {0x4b, 0xf9, 0x2f, 0x35, 0x77, 0xb3,
                                          0x4d, 0xa6, 0xa3, 0xce, 0x92, 0x9d,
                                          0x0e, 0x0e, 0x47, 0x36};
    const uint8_t span_bytes[8] = {0x00, 0xf0, 0x67, 0xaa, 0x0b, 0xa9,
                                        0x02, 0xb7};

    opentelemetry::trace::SpanContext sc(
        opentelemetry::trace::TraceId(trace_bytes),
        opentelemetry::trace::SpanId(span_bytes),
        opentelemetry::trace::TraceFlags(
            opentelemetry::trace::TraceFlags::kIsSampled),
        false
    );

    opentelemetry::nostd::shared_ptr<opentelemetry::trace::Span> span(
        new opentelemetry::trace::DefaultSpan(sc));

    opentelemetry::context::Context current =
        opentelemetry::context::RuntimeContext::GetCurrent();
    opentelemetry::context::Context ctx_with_span =
        opentelemetry::trace::SetSpan(current, span);
    opentelemetry::nostd::unique_ptr<opentelemetry::context::Token> token =
        opentelemetry::context::RuntimeContext::Attach(ctx_with_span);

    cJSON *obj = cJSON_CreateObject();
    tracing_inject(*obj);

    const cJSON *tp = cJSON_GetObjectItemCaseSensitive(obj, "traceparent");
    TEST_ASSERT_NOT_NULL(tp);
    TEST_ASSERT_TRUE(cJSON_IsString(tp));
    TEST_ASSERT_EQUAL_STRING(traceparent, tp->valuestring);

    cJSON_Delete(obj);
}

TEST_CASE("inject extract roundtrip", "[tracing]") {
    cJSON *in = cJSON_CreateObject();
    cJSON_AddStringToObject(in, "traceparent", traceparent);

    opentelemetry::context::Context ctx = tracing_extract(*in);
    cJSON_Delete(in);

    opentelemetry::nostd::unique_ptr<opentelemetry::context::Token> token =
        opentelemetry::context::RuntimeContext::Attach(ctx);

    cJSON *out = cJSON_CreateObject();
    tracing_inject(*out);

    const cJSON *tp = cJSON_GetObjectItemCaseSensitive(out, "traceparent");
    TEST_ASSERT_NOT_NULL(tp);
    TEST_ASSERT_TRUE(cJSON_IsString(tp));
    TEST_ASSERT_EQUAL_STRING(traceparent, tp->valuestring);

    cJSON_Delete(out);
}
