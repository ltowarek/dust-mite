#include "telemetry_types.hpp"
#include <cJSON.h>

cJSON* convert_telemetry_packet_to_json(const telemetry_packet_t &p) {
  cJSON* root=cJSON_CreateObject();
  cJSON_AddStringToObject(root, "timestamp", p.timestamp);
  cJSON_AddNumberToObject(root, "rssi", p.rssi);
  cJSON_AddNumberToObject(root, "speed", p.speed);

  cJSON* accelerometer=cJSON_AddObjectToObject(root, "accelerometer");
  cJSON_AddNumberToObject(accelerometer, "x", p.accelerometer.x);
  cJSON_AddNumberToObject(accelerometer, "y", p.accelerometer.y);
  cJSON_AddNumberToObject(accelerometer, "z", p.accelerometer.z);

  cJSON* magnetometer=cJSON_AddObjectToObject(root, "magnetometer");
  cJSON_AddNumberToObject(magnetometer, "x", p.magnetometer.x);
  cJSON_AddNumberToObject(magnetometer, "y", p.magnetometer.y);
  cJSON_AddNumberToObject(magnetometer, "z", p.magnetometer.z);

  cJSON* gyroscope=cJSON_AddObjectToObject(root, "gyroscope");
  cJSON_AddNumberToObject(gyroscope, "x", p.gyroscope.x);
  cJSON_AddNumberToObject(gyroscope, "y", p.gyroscope.y);
  cJSON_AddNumberToObject(gyroscope, "z", p.gyroscope.z);

  cJSON_AddNumberToObject(root, "distance_ahead", p.distance_ahead);

  return root;
}
