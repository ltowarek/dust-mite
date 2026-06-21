#include "motor.hpp"
#include "unity.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

extern "C" void app_main(void) {
  QueueHandle_t command_queue = xQueueCreate(2, sizeof(command_packet_t));
  motor_setup(command_queue);  // also calls servo_init() internally

  UNITY_BEGIN();
  unity_run_all_tests();
  UNITY_END();
}

void setUp(void) {}
void tearDown(void) {}
