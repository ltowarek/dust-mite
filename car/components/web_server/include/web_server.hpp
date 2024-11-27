#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

void wifi_setup(QueueHandle_t frame_queue, QueueHandle_t command_queue);
void web_server_setup(QueueHandle_t frame_queue, QueueHandle_t command_queue);

#ifdef __cplusplus
}
#endif
