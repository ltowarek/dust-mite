#pragma once

#include "telemetry_types.hpp"

void telemetry_metrics_setup();
void telemetry_metrics_update(const telemetry_reading_t& reading);
