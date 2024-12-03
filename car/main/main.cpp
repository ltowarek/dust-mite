// http://<IP>/?command=3&value=127

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_camera.h"
#include "camera.hpp"
#include "web_server.hpp"
#include "motor.hpp"
#include "telemetry.hpp"

extern "C" void app_main()
{
  QueueHandle_t command_queue = xQueueCreate(2, sizeof(command_packet_t));
  QueueHandle_t frame_queue = xQueueCreate(2, sizeof(camera_fb_t*));
  QueueHandle_t telemetry_queue = xQueueCreate(2, sizeof(telemetry_packet_t));

  motor_setup(command_queue);
  camera_setup(frame_queue);
  wifi_setup();
  telemetry_setup(telemetry_queue);
  web_server_setup(frame_queue, command_queue, telemetry_queue);
}
