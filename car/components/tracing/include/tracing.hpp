#pragma once

#include "esp_opentelemetry.hpp"
#include "opentelemetry/context/context.h"
#include "opentelemetry/trace/scope.h"
#include "opentelemetry/trace/span_startoptions.h"
#include <cJSON.h>

void tracing_setup();
void tracing_inject(cJSON& obj);
opentelemetry::context::Context tracing_extract(const cJSON& obj);
