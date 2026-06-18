#pragma once

#include <cstdint>

#include "opentelemetry/metrics/observer_result.h"

void observe_double(opentelemetry::metrics::ObserverResult& obs, double value);
void observe_int64(opentelemetry::metrics::ObserverResult& obs, int64_t value);
void metrics_setup();
