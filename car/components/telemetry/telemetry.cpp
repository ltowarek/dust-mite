#include "telemetry.hpp"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_sntp.h"
#include "esp_netif_sntp.h"
#include "esp_wifi.h"
#include "esp_timer.h"
#include <cJSON.h>
#include <time.h>
#include "driver/pulse_cnt.h"

static const char* TAG = "telemetry";

#define TELEMETRY_START_NOTIFICATION_INDEX 0
#define TELEMETRY_STOP_NOTIFICATION_INDEX 1

static QueueHandle_t g_telemetry_queue = NULL;
static TaskHandle_t g_telemetry_task_handle = NULL;

static pcnt_unit_handle_t g_pcnt_unit = NULL;

static uint64_t g_previous_timestamp = 0;

void sync_time() {
  ESP_LOGI(TAG, "Initializing SNTP");
  esp_sntp_config_t config = ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org");
  esp_netif_sntp_init(&config);

  time_t now = 0;
  while (esp_netif_sntp_sync_wait(2000 / portTICK_PERIOD_MS) == ESP_ERR_TIMEOUT) {
    ESP_LOGI(TAG, "Waiting for system time to be set...");
  }
  ESP_LOGI(TAG, "Set system time");
  time(&now);
}

void get_timestamp(char *buf) {
  time_t now;
  time(&now);
  tm timeinfo = {};
  gmtime_r(&now, &timeinfo);

  strftime(buf, (20+1) * sizeof(char), "%Y-%m-%dT%H:%M:%SZ", &timeinfo);
  buf[20] = '\0';
}

int get_rssi() {
  int rssi = 0;
  ESP_ERROR_CHECK(esp_wifi_sta_get_rssi(&rssi));
  return rssi;
}

void get_telemetry_packet(telemetry_packet_t *p) {
  get_timestamp(p->timestamp);
  p->rssi = get_rssi();
  p->speed = get_speed();
}

cJSON* convert_telemetry_packet_to_json(const telemetry_packet_t &p) {
  cJSON* root=cJSON_CreateObject();
  cJSON_AddStringToObject(root, "timestamp", p.timestamp);
  cJSON_AddNumberToObject(root, "rssi", p.rssi);
  cJSON_AddNumberToObject(root, "speed", p.speed);
  return root;
}

void pcnt_init() {
  const int pcnt_limit = 20;

  pcnt_unit_config_t pcnt_config = {};
  pcnt_config.high_limit = pcnt_limit;
  pcnt_config.low_limit = -pcnt_limit;
  pcnt_config.flags.accum_count = 1;
  ESP_ERROR_CHECK(pcnt_new_unit(&pcnt_config, &g_pcnt_unit));

  pcnt_chan_config_t pcnt_channel_config = {};
  pcnt_channel_config.edge_gpio_num = 18;
  pcnt_channel_config.level_gpio_num = -1;
  pcnt_channel_config.flags.virt_level_io_level = 1;
  pcnt_channel_handle_t pcnt_channel = NULL;
  ESP_ERROR_CHECK(pcnt_new_channel(g_pcnt_unit, &pcnt_channel_config, &pcnt_channel));

  ESP_ERROR_CHECK(pcnt_channel_set_edge_action(pcnt_channel, PCNT_CHANNEL_EDGE_ACTION_HOLD, PCNT_CHANNEL_EDGE_ACTION_INCREASE));
  ESP_ERROR_CHECK(pcnt_unit_add_watch_point(g_pcnt_unit, pcnt_limit));
  ESP_ERROR_CHECK(pcnt_unit_clear_count(g_pcnt_unit));
  ESP_ERROR_CHECK(pcnt_unit_enable(g_pcnt_unit));
  ESP_ERROR_CHECK(pcnt_unit_start(g_pcnt_unit));
}

void reset_pcnt() {
  g_previous_timestamp = esp_timer_get_time();
  ESP_ERROR_CHECK(pcnt_unit_clear_count(g_pcnt_unit));
}

int get_counter() {
  int pulses = 0;
  ESP_ERROR_CHECK(pcnt_unit_get_count(g_pcnt_unit, &pulses));
  ESP_ERROR_CHECK(pcnt_unit_clear_count(g_pcnt_unit));
  return pulses;
}

float get_pps() {
  int pulses = get_counter();
  uint64_t current_timestamp = (uint64_t)esp_timer_get_time();
  float duration_s = (float)(current_timestamp - g_previous_timestamp) / 1000000.0f;
  g_previous_timestamp = current_timestamp;
  float pulses_per_second = pulses / duration_s;
  return pulses_per_second;
}

float get_rpm() {
  float pulses_per_second = get_pps();
  int encoder_slots = 20;
  float revolutions_per_second = pulses_per_second / encoder_slots;
  float revolutions_per_minute = revolutions_per_second * 60;
  return revolutions_per_minute;

}

float get_speed() {
  float revolutions_per_minute = get_rpm();
  float wheel_diameter_m = 0.066f;  // 6,6 cm
  // S = RPM * DIAMETER_IN_METERS * PI * MINUTES_IN_HOUR/METERS_IN_KILOMETER
  float velocity_kph = revolutions_per_minute * wheel_diameter_m * 3.14f * 60/1000;
  ESP_LOGI(TAG, "velocity: %f", velocity_kph);
  return velocity_kph;
}

void telemetry_init() {
  sync_time();
  pcnt_init();
}

void telemetry_task(void* p) {
  ESP_LOGI(TAG, "Starting telemetry task");
  bool started = false;
  while (true) {
    if (!started) {
      ESP_LOGI(TAG, "Waiting for notification to start telemetry");
      ulTaskNotifyTakeIndexed(TELEMETRY_START_NOTIFICATION_INDEX, pdTRUE, portMAX_DELAY);
      started = true;
      reset_pcnt();
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

    vTaskDelay(500 / portTICK_PERIOD_MS);
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
}

void telemetry_start() {
  xTaskNotifyGiveIndexed(g_telemetry_task_handle, TELEMETRY_START_NOTIFICATION_INDEX);
}

void telemetry_stop() {
  xTaskNotifyGiveIndexed(g_telemetry_task_handle, TELEMETRY_STOP_NOTIFICATION_INDEX);
}
