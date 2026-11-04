#pragma once

#include <cstdint>

// Each endpoint runs its own HTTP server instance on its own port, so a client that reads one
// endpoint slowly cannot delay another (docs/adr/0001-one-http-server-per-car-endpoint.md).
constexpr uint16_t WEB_SERVER_DRIVE_PORT = 80;
constexpr uint16_t WEB_SERVER_CAMERA_PORT = 81;
constexpr uint16_t WEB_SERVER_TELEMETRY_PORT = 82;

#ifdef __cplusplus
extern "C" {
#endif

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "motor.hpp"

void web_server_setup(QueueHandle_t frame_queue, QueueHandle_t command_queue,
                      QueueHandle_t telemetry_queue);
void web_server_wait_for_serving();

bool parse_drive_command(const char* json, drive_command_t* out);

#ifdef __cplusplus
}
#endif
