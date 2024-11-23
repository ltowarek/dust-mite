// http://<IP>/?command=3&value=127

#include "freertos/FreeRTOS.h"
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

camera_fb_t* camera_frame = NULL;
frame_t* server_frame = NULL;

frame_t* frame_get_handler() {
  camera_frame = camera_fb_get();
  server_frame = (frame_t*)malloc(sizeof(frame_t));
  server_frame->buf = camera_frame->buf;
  server_frame->len = camera_frame->len;
  return server_frame;
}

void frame_return_handler(frame_t *frame) {
  camera_fb_return(camera_frame);
  camera_frame = NULL;

  free(server_frame);
  server_frame = NULL;
}

void setup()
{
  camera_setup();
  motor_setup();
  wifi_setup();
  register_command_handler(command_handler);
  register_frame_get_handler(frame_get_handler);
  register_frame_return_handler(frame_return_handler);
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
