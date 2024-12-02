#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

typedef struct {
  char timestamp[17+1];
} telemetry_packet_t;

void telemetry_init();
void telemetry_setup(QueueHandle_t telemetry_queue);
void telemetry_start();
void telemetry_stop();

#ifdef __cplusplus
}
#endif
