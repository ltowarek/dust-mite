#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_camera.h"

void camera_init();
void camera_setup(QueueHandle_t frame_queue);
void camera_start();
void camera_stop();

#ifdef __cplusplus
}
#endif
