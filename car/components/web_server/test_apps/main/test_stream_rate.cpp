#include <cstdint>
#include <cstdio>
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "stream_client.hpp"
#include "unity.h"

// The camera delivers about 25 frames per second; the stream may lose at most one of them.
static const int MIN_STREAM_FPS = 24;
static const int STREAM_RATE_WINDOW_MS = 20000;

TEST_CASE("stream_keeps_the_camera_rate", "[web_server]") {
  stream_client_t* client = stream_open_or_fail();
  wait_for_count(client->parts, 1, FIRST_FRAME_BUDGET_MS);
  int first = client->parts;
  int64_t start = esp_timer_get_time();
  vTaskDelay(pdMS_TO_TICKS(STREAM_RATE_WINDOW_MS));
  int parts = client->parts - first;
  int64_t elapsed_us = esp_timer_get_time() - start;
  int fps = static_cast<int>(static_cast<int64_t>(parts) * 1000000 / elapsed_us);
  printf("%d parts in %lld us (%d frames per second)\n", parts, elapsed_us, fps);

  TEST_ASSERT_GREATER_OR_EQUAL(MIN_STREAM_FPS, fps);
}
