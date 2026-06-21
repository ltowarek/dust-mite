#include "web_server.hpp"
#include "motor.hpp"
#include <cJSON.h>

bool parse_command_packet(const char* json, command_packet_t* out) {
  if (!json || !out) return false;
  cJSON* root = cJSON_Parse(json);
  if (!root) return false;
  cJSON* cmd_obj = cJSON_GetObjectItem(root, "command");
  cJSON* val_obj = cJSON_GetObjectItem(root, "value");
  out->command = cJSON_IsNumber(cmd_obj) ? (char)cJSON_GetNumberValue(cmd_obj) : 0;
  out->value = cJSON_IsNumber(val_obj) ? (int)cJSON_GetNumberValue(val_obj) : 0;
  cJSON_Delete(root);
  return true;
}
