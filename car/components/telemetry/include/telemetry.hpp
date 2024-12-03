#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include <cJSON.h>

typedef struct {
  char timestamp[20+1];
} telemetry_packet_t;

void telemetry_init();
void telemetry_setup(QueueHandle_t telemetry_queue);
void telemetry_start();
void telemetry_stop();

cJSON* convert_telemetry_packet_to_json(const telemetry_packet_t &p);

#ifdef __cplusplus
}
#endif
