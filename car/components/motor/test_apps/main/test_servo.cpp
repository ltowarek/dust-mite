#include "servo.hpp"
#include "unity.h"
#include "esp_log.h"

TEST_CASE("pan", "[servo]") {
  int angle = 0;
  ESP_LOGI("test", "Angle: %d", angle);
  move_pan(angle);
  vTaskDelay(pdMS_TO_TICKS(1000));

  angle = 90;
  ESP_LOGI("test", "Angle: %d", angle);
  move_pan(angle);
  vTaskDelay(pdMS_TO_TICKS(1000));

  angle = -90;
  ESP_LOGI("test", "Angle: %d", angle);
  move_pan(angle);
  vTaskDelay(pdMS_TO_TICKS(1000));

  angle = 0;
  ESP_LOGI("test", "Angle: %d", angle);
  move_pan(angle);
  vTaskDelay(pdMS_TO_TICKS(1000));
}

TEST_CASE("tilt", "[servo]") {
  int angle = 0;
  ESP_LOGI("test", "Angle: %d", angle);
  move_tilt(angle);
  vTaskDelay(pdMS_TO_TICKS(1000));

  angle = 90;
  ESP_LOGI("test", "Angle: %d", angle);
  move_tilt(angle);
  vTaskDelay(pdMS_TO_TICKS(1000));

  angle = -90;
  ESP_LOGI("test", "Angle: %d", angle);
  move_tilt(angle);
  vTaskDelay(pdMS_TO_TICKS(1000));

  angle = 0;
  ESP_LOGI("test", "Angle: %d", angle);
  move_tilt(angle);
  vTaskDelay(pdMS_TO_TICKS(1000));
}
