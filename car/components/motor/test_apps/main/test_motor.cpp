#include "motor.hpp"
#include "unity.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

TEST_CASE("advance", "[motor]") {
  car_advance(50);
  vTaskDelay(pdMS_TO_TICKS(1000));
  car_brake();
}
TEST_CASE("retreat", "[motor]") {
  car_retreat(50);
  vTaskDelay(pdMS_TO_TICKS(1000));
  car_brake();
}
TEST_CASE("brake", "[motor]") {
  car_advance(50);
  vTaskDelay(pdMS_TO_TICKS(500));
  car_brake();
}
TEST_CASE("turn_left", "[motor]") {
  car_turn_left(50);
  vTaskDelay(pdMS_TO_TICKS(1000));
  car_brake();
}
TEST_CASE("turn_right", "[motor]") {
  car_turn_right(50);
  vTaskDelay(pdMS_TO_TICKS(1000));
  car_brake();
}
