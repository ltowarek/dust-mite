#pragma once

#include "opentelemetry/metrics/observer_result.h"

void observe_double(opentelemetry::metrics::ObserverResult& obs, double value);
void metrics_setup();
