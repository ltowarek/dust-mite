#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include <cJSON.h>

typedef struct {
  float x;
  float y;
  float z;
} vector3_t;

typedef struct {
  char timestamp[20+1];
  int rssi;
  float speed;
  vector3_t accelerometer;
  vector3_t magnetometer;
  vector3_t gyroscope;
} telemetry_packet_t;

void telemetry_init();
void telemetry_setup(QueueHandle_t telemetry_queue);
void telemetry_start();
void telemetry_stop();

int get_rssi();
float get_speed();
vector3_t read_accelerometer();
vector3_t read_magnetometer();
vector3_t read_gyroscope();
// TODO: Compute roll/pitch/yaw - https://github.com/adafruit/Adafruit_AHRS

cJSON* convert_telemetry_packet_to_json(const telemetry_packet_t &p);

#ifdef __cplusplus
}
#endif
