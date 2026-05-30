#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "motor.hpp"

void web_server_setup(QueueHandle_t frame_queue, QueueHandle_t command_queue, QueueHandle_t telemetry_queue);

bool parse_command_packet(const char *json, command_packet_t *out);

#ifdef __cplusplus
}
#endif
