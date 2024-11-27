#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_camera.h"

void camera_setup(QueueHandle_t frame_queue);

#ifdef __cplusplus
}
#endif
