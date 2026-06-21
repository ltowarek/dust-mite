#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include <cJSON.h>

typedef struct {
  float x;
  float y;
  float z;
} vector3_t;

typedef struct {
  char timestamp[20 + 1];
  int rssi;
  float speed;
  vector3_t accelerometer;
  vector3_t magnetometer;
  vector3_t gyroscope;
  int distance_ahead;
} telemetry_packet_t;

cJSON* convert_telemetry_packet_to_json(const telemetry_packet_t& p);

#ifdef __cplusplus
}
#endif
