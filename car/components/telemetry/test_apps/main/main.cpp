#include "telemetry.hpp"
#include "unity.h"
#include "driver/gpio.h"
#include "sdkconfig.h"
#ifdef CONFIG_TELEMETRY_TEST_COVERAGE
#include "gcov_uart_vfs.h"
#endif

extern "C" void app_main(void) {
#ifndef CONFIG_TELEMETRY_TEST_QEMU_MODE
  i2c_master_bus_config_t bus_cfg = {};
  bus_cfg.i2c_port = I2C_NUM_0;
  bus_cfg.sda_io_num = GPIO_NUM_1;
  bus_cfg.scl_io_num = GPIO_NUM_2;
  bus_cfg.clk_source = I2C_CLK_SRC_DEFAULT;
  bus_cfg.glitch_ignore_cnt = 7;
  bus_cfg.flags.enable_internal_pullup = true;
  i2c_master_bus_handle_t i2c_bus;
  ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &i2c_bus));
  telemetry_init(i2c_bus);
#endif

  UNITY_BEGIN();
  unity_run_all_tests();
  UNITY_END();
#ifdef CONFIG_TELEMETRY_TEST_COVERAGE
  gcov_uart_vfs_dump();
#endif
}

void setUp(void) {}
void tearDown(void) {}
