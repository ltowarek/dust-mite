#include "stdio.h"
#include "camera.hpp"
#include "unity.h"
#include "esp_timer.h"
#include "esp_camera.h"
#include "driver/gpio.h"

extern "C" void app_main(void) {
  i2c_master_bus_config_t bus_cfg = {};
  bus_cfg.i2c_port = I2C_NUM_0;
  bus_cfg.sda_io_num = GPIO_NUM_1;
  bus_cfg.scl_io_num = GPIO_NUM_2;
  bus_cfg.clk_source = I2C_CLK_SRC_DEFAULT;
  bus_cfg.glitch_ignore_cnt = 7;
  bus_cfg.flags.enable_internal_pullup = true;
  i2c_master_bus_handle_t i2c_bus;
  ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &i2c_bus));
  camera_init(i2c_bus);

  UNITY_BEGIN();
  unity_run_all_tests();
  UNITY_END();
}

void setUp(void) {}
void tearDown(void) {}

TEST_CASE("performance", "[camera]") {
  const unsigned MEASUREMENTS = 100;

  uint64_t start = esp_timer_get_time();
  for (int i = 0; i < MEASUREMENTS; i++) {
    camera_fb_t* frame = esp_camera_fb_get();
    esp_camera_fb_return(frame);
  }
  uint64_t end = esp_timer_get_time();

  int fps = (int)((uint64_t)MEASUREMENTS * 1000000ULL / (end - start));

  printf("%u iterations took %llu us (%d frames per second)\n", MEASUREMENTS, end - start, fps);

  TEST_ASSERT_INT_WITHIN(5, 25, fps);
}

TEST_CASE("throughput", "[camera]") {
  const unsigned MEASUREMENTS = 100;

  size_t frame_sizes = 0;

  uint64_t start = esp_timer_get_time();
  for (int i = 0; i < MEASUREMENTS; i++) {
    camera_fb_t* frame = esp_camera_fb_get();
    frame_sizes += frame->len;
    esp_camera_fb_return(frame);
  }
  uint64_t end = esp_timer_get_time();

  int throughput_mbps = (int)((uint64_t)frame_sizes * 8ULL / (end - start));

  printf("%u iterations took %llu us with total frame size of %zu bytes (%d MBit/s)\n",
         MEASUREMENTS, end - start, frame_sizes, throughput_mbps);

  TEST_ASSERT_GREATER_THAN(1, throughput_mbps);
}

TEST_CASE("single_frame", "[camera]") {
  camera_fb_t* frame = esp_camera_fb_get();
  TEST_ASSERT_NOT_NULL(frame);
  TEST_ASSERT_GREATER_OR_EQUAL(2, frame->len);
  TEST_ASSERT_EQUAL_HEX8(0xFF, frame->buf[0]);
  TEST_ASSERT_EQUAL_HEX8(0xD8, frame->buf[1]);
  TEST_ASSERT_EQUAL_HEX8(0xFF, frame->buf[frame->len - 2]);
  TEST_ASSERT_EQUAL_HEX8(0xD9, frame->buf[frame->len - 1]);
  esp_camera_fb_return(frame);
}

TEST_CASE("dma_stress", "[camera]") {
  // Hold one frame buffer for 200 ms while the camera keeps producing to stress
  // the DMA pool with fb_count=2 (slow consumer vs. fast producer).
  camera_fb_t* frame1 = esp_camera_fb_get();
  TEST_ASSERT_NOT_NULL(frame1);

  vTaskDelay(pdMS_TO_TICKS(200));

  // With CAMERA_GRAB_LATEST and one buffer held, the second slot should still
  // be available and deliver a valid frame.
  camera_fb_t* frame2 = esp_camera_fb_get();
  TEST_ASSERT_NOT_NULL(frame2);
  TEST_ASSERT_GREATER_OR_EQUAL(2, frame2->len);
  TEST_ASSERT_EQUAL_HEX8(0xFF, frame2->buf[0]);
  TEST_ASSERT_EQUAL_HEX8(0xD8, frame2->buf[1]);

  esp_camera_fb_return(frame1);
  esp_camera_fb_return(frame2);
}
