#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "driver/i2c_master.h"
#include "esp_camera.h"
#include "camera.hpp"
#include "web_server.hpp"
#include "web_server_metrics.hpp"
#include "test_app.hpp"
#include "motor.hpp"
#include "esp_opentelemetry.hpp"
#include "wifi.hpp"
#include "telemetry.hpp"
#include "unity.h"
#include "esp_log.h"
#include "sdkconfig.h"
#ifdef CONFIG_WEB_SERVER_TEST_QEMU_MODE
#include "qemu_peripherals.hpp"
#endif
#ifdef CONFIG_WEB_SERVER_TEST_COVERAGE
extern "C" {
#include "esp_gcov.h"
}
#endif

#ifndef CONFIG_WEB_SERVER_TEST_QEMU_MODE
static i2c_master_bus_handle_t i2c_bus_init() {
  i2c_master_bus_config_t bus_cfg = {};
  bus_cfg.i2c_port = I2C_NUM_0;
  bus_cfg.sda_io_num = GPIO_NUM_1;
  bus_cfg.scl_io_num = GPIO_NUM_2;
  bus_cfg.clk_source = I2C_CLK_SRC_DEFAULT;
  bus_cfg.glitch_ignore_cnt = 7;
  bus_cfg.flags.enable_internal_pullup = true;
  i2c_master_bus_handle_t bus = nullptr;
  ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));
  return bus;
}
#endif

QueueHandle_t test_app_command_queue = nullptr;

extern "C" void app_main(void) {
  QueueHandle_t command_queue = xQueueCreate(1, sizeof(drive_command_t));
  test_app_command_queue = command_queue;
  QueueHandle_t frame_queue = xQueueCreate(1, sizeof(camera_fb_t*));
  QueueHandle_t telemetry_queue = xQueueCreate(2, sizeof(telemetry_reading_t));

#ifndef CONFIG_WEB_SERVER_TEST_QEMU_MODE
  i2c_master_bus_handle_t i2c_bus = i2c_bus_init();

  esp_opentelemetry_tracing_setup({{"service.name", CONFIG_ESP_OPENTELEMETRY_SERVICE_NAME}});
  wifi_setup();
  camera_setup(frame_queue, i2c_bus);
  telemetry_setup(telemetry_queue, i2c_bus);
  web_server_setup(frame_queue, command_queue, telemetry_queue);
  // The server stops whenever the car loses Wi-Fi, so the cases start only once it has connected.
  wifi_wait_for_ip();
#else
  qemu_ethernet_setup();
  web_server_setup(frame_queue, command_queue, telemetry_queue);
  qemu_producers_setup(frame_queue, telemetry_queue);
#endif
  web_server_metrics_setup();

  unity_run_menu();
}

void setUp(void) {}

// Unity prints the result line one character at a time, so a log line from a server task that is
// still closing a connection would land inside it and the runner would misread the result. A line
// a task has already started is let finish before the result is printed.
void tearDown(void) {
  const int log_drain_ms = 100;
  esp_log_level_set("*", ESP_LOG_NONE);
  vTaskDelay(pdMS_TO_TICKS(log_drain_ms));
#ifdef CONFIG_WEB_SERVER_TEST_COVERAGE
  esp_gcov_dump();
#endif
}
