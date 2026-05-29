#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "driver/i2c_master.h"

void camera_init(i2c_master_bus_handle_t i2c_bus);
void camera_setup(QueueHandle_t frame_queue, i2c_master_bus_handle_t i2c_bus);
void camera_start();
void camera_stop();

#ifdef __cplusplus
}
#endif
