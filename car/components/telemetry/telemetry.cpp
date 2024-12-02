#include "telemetry.hpp"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include <time.h>

static const char* TAG = "telemetry";

#define TELEMETRY_START_NOTIFICATION_INDEX 0
#define TELEMETRY_STOP_NOTIFICATION_INDEX 1

static QueueHandle_t g_telemetry_queue = NULL;
static TaskHandle_t g_telemetry_task_handle = NULL;

void sync_time() {
  // Get data from sntp
  // Move it to wifi_setup?
}

void get_timestamp(char *buf) {
  time_t now;
  time(&now);
  tm timeinfo = {};
  gmtime_r(&now, &timeinfo);

  strftime(buf, (17+1) * sizeof(char), "%Y-%m-%dT%H:%MZ", &timeinfo);
  buf[17] = '\0';
}

void get_telemetry_packet(telemetry_packet_t *p) {
  get_timestamp(p->timestamp);
}

void telemetry_init() {
  sync_time();
}

void telemetry_task(void* p) {
  ESP_LOGI(TAG, "Starting telemetry task");
  bool started = false;
  while (true) {
    if (!started) {
      ESP_LOGI(TAG, "Waiting for notification to start telemetry");
      ulTaskNotifyTakeIndexed(TELEMETRY_START_NOTIFICATION_INDEX, pdTRUE, portMAX_DELAY);
      started = true;
      ESP_LOGI(TAG, "Telemetry started");
    }

    if (ulTaskNotifyTakeIndexed(TELEMETRY_STOP_NOTIFICATION_INDEX, pdTRUE, 0) == 1) {
      started = false;
      ESP_LOGI(TAG, "Telemetry stopped");
      continue;
    }

    telemetry_packet_t packet = {};
    get_telemetry_packet(&packet);

    if (xQueueSendToBack(g_telemetry_queue, &packet, portMAX_DELAY) != pdPASS) {
      ESP_LOGE(TAG, "xQueueSendToBack failed");
      break;
    }
  }
  ESP_LOGW(TAG, "Telemetry task stopped");
  vTaskDelete(NULL);
}

void telemetry_setup(QueueHandle_t telemetry_queue) {
  g_telemetry_queue = telemetry_queue;

  telemetry_init();

  if (xTaskCreate(telemetry_task, "telemetry_task", 4096, (void *)0, 1, &g_telemetry_task_handle) != pdPASS) {
    ESP_LOGE(TAG, "xTaskCreate(telemetry_task) failed");
    return;
  }

  char x[17+1];
  get_timestamp(x);
  ESP_LOGI(TAG, "FOO: %s", x);
}

void telemetry_start() {
  xTaskNotifyGiveIndexed(g_telemetry_task_handle, TELEMETRY_START_NOTIFICATION_INDEX);
}

void telemetry_stop() {
  xTaskNotifyGiveIndexed(g_telemetry_task_handle, TELEMETRY_STOP_NOTIFICATION_INDEX);
}
