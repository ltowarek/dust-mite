#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "driver/i2c_master.h"
#include "esp_camera.h"
#include "camera.hpp"
#include "web_server.hpp"
#include "motor.hpp"
#include "esp_opentelemetry.hpp"
#include "wifi.hpp"
#include "telemetry.hpp"
#include "unity.h"
#include "sdkconfig.h"
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

extern "C" void app_main(void) {
  QueueHandle_t command_queue = xQueueCreate(2, sizeof(command_packet_t));
  QueueHandle_t frame_queue = xQueueCreate(2, sizeof(camera_fb_t*));
  QueueHandle_t telemetry_queue = xQueueCreate(2, sizeof(telemetry_packet_t));

#ifndef CONFIG_WEB_SERVER_TEST_QEMU_MODE
  i2c_master_bus_handle_t i2c_bus = i2c_bus_init();

  motor_setup(command_queue);
  esp_opentelemetry_tracing_setup({{"service.name", CONFIG_ESP_OPENTELEMETRY_SERVICE_NAME}});
  wifi_setup();
  camera_setup(frame_queue, i2c_bus);
  telemetry_setup(telemetry_queue, i2c_bus);
  web_server_setup(frame_queue, command_queue, telemetry_queue);
#endif

  UNITY_BEGIN();
  unity_run_all_tests();
  UNITY_END();
#ifdef CONFIG_WEB_SERVER_TEST_COVERAGE
  esp_gcov_dump();
  printf("GCOV_DUMP_DONE\n");
#endif
}

void setUp(void) {}
void tearDown(void) {}
