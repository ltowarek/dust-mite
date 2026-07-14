#pragma once

#include "opentelemetry/context/context.h"
#include <cJSON.h>

void tracing_inject(cJSON& obj);
opentelemetry::context::Context tracing_extract(const cJSON& obj);
