// http://<IP>/?command=3&value=127

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_camera.h"
#include "driver/i2c_master.h"
#include "camera.hpp"
#include "camera_metrics.hpp"
#include "web_server.hpp"
#include "web_server_metrics.hpp"
#include "motor.hpp"
#include "telemetry.hpp"
#include "telemetry_metrics.hpp"
#include "tracing.hpp"
#include "system_metrics.hpp"
#include "wifi.hpp"
#include "sdkconfig.h"

static i2c_master_bus_handle_t i2c_bus_init() {
  i2c_master_bus_config_t bus_cfg = {};
  bus_cfg.i2c_port = I2C_NUM_0;
  bus_cfg.sda_io_num = GPIO_NUM_1;
  bus_cfg.scl_io_num = GPIO_NUM_2;
  bus_cfg.clk_source = I2C_CLK_SRC_DEFAULT;
  bus_cfg.glitch_ignore_cnt = 7;
  bus_cfg.flags.enable_internal_pullup = true;
  i2c_master_bus_handle_t bus;
  ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));
  return bus;
}

extern "C" void app_main() {
  QueueHandle_t command_queue = xQueueCreate(2, sizeof(command_packet_t));
  QueueHandle_t frame_queue = xQueueCreate(2, sizeof(camera_fb_t*));
  QueueHandle_t telemetry_queue = xQueueCreate(2, sizeof(telemetry_packet_t));

  i2c_master_bus_handle_t i2c_bus = i2c_bus_init();

  wifi_setup();
  wifi_wait_for_ip();
  sync_time();

  motor_setup(command_queue);
  camera_setup(frame_queue, i2c_bus);
  telemetry_setup(telemetry_queue, i2c_bus);
  web_server_setup(frame_queue, command_queue, telemetry_queue);

  tracing_setup();

  metrics_setup();
  system_metrics_setup();
  telemetry_metrics_setup();
  camera_metrics_setup();
  web_server_metrics_setup();
}
