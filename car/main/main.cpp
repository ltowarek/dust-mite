// http://<IP>/?command=3&value=127

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "camera.hpp"
#include "web_server.hpp"
#include "motor.hpp"

static const char* TAG = "car";

extern "C" void app_main()
{
  QueueHandle_t command_queue = xQueueCreate(2, sizeof(command_packet_t));
  QueueHandle_t frame_queue = xQueueCreate(2, sizeof(camera_fb_t*));

  motor_setup(command_queue);
  camera_setup(frame_queue);
  wifi_setup(frame_queue, command_queue);
}
