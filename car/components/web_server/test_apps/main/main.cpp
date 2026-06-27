#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "web_server.hpp"
#include "motor.hpp"
#include "tracing.hpp"
#include "wifi.hpp"
#include "telemetry.hpp"
#include "unity.h"
#include "sdkconfig.h"
#ifdef CONFIG_WEB_SERVER_TEST_COVERAGE
#include "gcov_uart_vfs.h"
#endif

extern "C" void app_main(void) {
  QueueHandle_t command_queue = xQueueCreate(2, sizeof(command_packet_t));
  QueueHandle_t frame_queue = xQueueCreate(2, sizeof(void*));
  QueueHandle_t telemetry_queue = xQueueCreate(2, sizeof(telemetry_packet_t));

#ifndef CONFIG_WEB_SERVER_TEST_QEMU_MODE
  motor_setup(command_queue);
  tracing_setup();
  wifi_setup();
  web_server_setup(frame_queue, command_queue, telemetry_queue);
#endif

  UNITY_BEGIN();
  unity_run_all_tests();
  UNITY_END();
#ifdef CONFIG_WEB_SERVER_TEST_COVERAGE
  gcov_uart_vfs_dump();
#endif
}

void setUp(void) {}
void tearDown(void) {}
