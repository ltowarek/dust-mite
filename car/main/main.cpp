// http://<IP>/?command=3&value=127

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "camera.hpp"
#include "web_server.hpp"
#include "motor.hpp"

static const char* TAG = "car";

static QueueHandle_t g_command_queue = NULL;
static TaskHandle_t g_command_task_handle = NULL;

static QueueHandle_t g_frame_queue = NULL;
static TaskHandle_t g_camera_task_handle = NULL;

void start_tasks() {
  if (xTaskCreate(command_task, "command_task", 4096, (void *)0, 1, &g_command_task_handle) != pdPASS) {
    ESP_LOGE(TAG, "xTaskCreate(command_task) failed");
    return;
  }
  if (xTaskCreate(camera_task, "camera_task", 4096, (void *)0, 1, &g_camera_task_handle) != pdPASS) {
    ESP_LOGE(TAG, "xTaskCreate(camera_task) failed");
    return;
  }
}

extern "C" void app_main()
{
  g_command_queue = xQueueCreate(2, sizeof(command_packet_t));
  g_frame_queue = xQueueCreate(2, sizeof(camera_fb_t*));

  motor_setup(g_command_queue);
  camera_setup(g_frame_queue);
  wifi_setup();
  web_server_setup(g_frame_queue, g_command_queue);

  start_tasks();
}
