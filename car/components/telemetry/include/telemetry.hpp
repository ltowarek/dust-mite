#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include "telemetry_types.hpp"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "driver/i2c_master.h"

void sync_time();
void telemetry_init(i2c_master_bus_handle_t i2c_bus);
void telemetry_setup(QueueHandle_t telemetry_queue, i2c_master_bus_handle_t i2c_bus);
void telemetry_start();
void telemetry_stop();

int get_rssi();
float get_speed();
vector3_t read_accelerometer();
vector3_t read_magnetometer();
vector3_t read_gyroscope();
// TODO: Compute roll/pitch/yaw - https://github.com/adafruit/Adafruit_AHRS
int get_distance_ahead();

#ifdef __cplusplus
}
#endif
