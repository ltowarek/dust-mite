// http://<IP>/?command=3&value=127

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "camera.hpp"
#include "web_server.hpp"
#include "motor.hpp"

static const char* TAG = "car";

#define COMMAND_ADVANCE 1
#define COMMAND_RETREAT 2
#define COMMAND_BRAKE 3
#define COMMAND_TURN_LEFT 4
#define COMMAND_TURN_RIGHT 5

static char g_command = 0;
static int g_value = 0;

static QueueHandle_t g_frame_queue = NULL;
static TaskHandle_t g_camera_task_handle = NULL;

void command_handler(char command, int *value) {
  if (command >= 1 && command <= 5) {
    g_command = command;
  } else {
    ESP_LOGW(TAG, "Unknown command: %d", command);
  }

  if (value != NULL) {
    g_value = *value;
  }
}

void start_tasks() {
  if (xTaskCreate(camera_task, "camera_task", 4096, (void *)0, 5, &g_camera_task_handle) != pdPASS) {
    ESP_LOGE(TAG, "xTaskCreate failed");
    return;
  }
}

void setup()
{
  g_frame_queue = xQueueCreate(2, sizeof(camera_fb_t*));

  camera_setup(g_frame_queue);
  motor_setup();
  wifi_setup();
  web_server_setup(g_frame_queue);
  register_command_handler(command_handler);

  start_tasks();
}

void loop()
{
  if (g_command != 0) {
    switch (g_command) {
      case COMMAND_ADVANCE:
        ESP_LOGI(TAG, "COMMAND_ADVANCE");
        car_advance(g_value);
        break;
      case COMMAND_RETREAT:
        ESP_LOGI(TAG, "COMMAND_RETREAT");
        car_retreat(g_value);
        break;
      case COMMAND_BRAKE:
        ESP_LOGI(TAG, "COMMAND_BRAKE");
        car_brake();
        break;
      case COMMAND_TURN_LEFT:
        ESP_LOGI(TAG, "COMMAND_TURN_LEFT");
        car_turn_left(g_value);
        break;
      case COMMAND_TURN_RIGHT:
        ESP_LOGI(TAG, "COMMAND_TURN_RIGHT");
        car_turn_right(g_value);
        break;
      default:
        ESP_LOGI(TAG, "Unknown command");
    }
    g_command = 0;
    g_value = 0;
  }

  vTaskDelay(10/portTICK_PERIOD_MS);
}

extern "C" void app_main()
{
  setup();
  while(true){
    loop();
  }
}
