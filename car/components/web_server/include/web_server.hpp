#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

void wifi_setup();
void web_server_setup(QueueHandle_t frame_queue);

void register_command_handler(void (*handler)(char, int*));

#ifdef __cplusplus
}
#endif
