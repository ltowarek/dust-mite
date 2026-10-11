#pragma once

#include "opentelemetry/context/context.h"
#include <cJSON.h>

// cJSON is taken by pointer, not by reference: ESP-IDF's malloc aligns cJSON nodes to only 4 bytes
// (https://github.com/espressif/esp-idf/issues/18685), while cJSON holds a double and needs 8, and
// binding a reference to such a node is undefined behaviour that UBSan reports.
void tracing_inject(cJSON* obj);
opentelemetry::context::Context tracing_extract(const cJSON* obj);
