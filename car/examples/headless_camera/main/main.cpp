#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "esp_camera.h"
#include "camera.hpp"
#include "wifi.hpp"
#include "tracing.hpp"

static QueueHandle_t g_frame_queue = NULL;

void consumer_task(void* p) {
  camera_fb_t* frame = NULL;
  while (true) {
    if (xQueueReceive(g_frame_queue, &frame, portMAX_DELAY) != pdPASS) {
      break;
    }
    // Hold the buffer to stress the DMA pool (fb_count=2)
    vTaskDelay(pdMS_TO_TICKS(200));
    esp_camera_fb_return(frame);
  }
  vTaskDelete(NULL);
}

extern "C" void app_main() {
  wifi_setup();
  tracing_setup();

  g_frame_queue = xQueueCreate(2, sizeof(camera_fb_t*));
  camera_setup(g_frame_queue);
  camera_start();

  xTaskCreate(consumer_task, "consumer_task", 8192, NULL, 5, NULL);
}
