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
#include "driver/i2c.h"

static const char* TAG = "telemetry";

#define TELEMETRY_START_NOTIFICATION_INDEX 0
#define TELEMETRY_STOP_NOTIFICATION_INDEX 1

static QueueHandle_t g_telemetry_queue = NULL;
static TaskHandle_t g_telemetry_task_handle = NULL;

static pcnt_unit_handle_t g_pcnt_unit = NULL;

static uint64_t g_previous_timestamp = 0;

static i2c_port_t g_i2c_port = I2C_NUM_1;

// Based on:
// https://github.com/adafruit/Adafruit_LSM9DS0_Library/
// https://github.com/sparkfun/LSM9DS0_Breakout/
#define LSM9DS0_XM_ADDRESS 0x1D
#define LSM9DS0_G_ADDRESS 0x6B
#define LSM9DS0_XM_ID 0x49
#define LSM9DS0_G_ID 0xD4
#define LSM9DS0_REGISTER_WHO_AM_I_XM 0x0F
#define LSM9DS0_REGISTER_WHO_AM_I_G 0x0F
#define LSM9DS0_REGISTER_CTRL_REG1_XM 0x20
#define LSM9DS0_REGISTER_CTRL_REG5_XM 0x24
#define LSM9DS0_REGISTER_CTRL_REG6_XM 0x25
#define LSM9DS0_REGISTER_CTRL_REG7_XM 0x26
#define LSM9DS0_REGISTER_CTRL_REG1_G 0x20
#define LSM9DS0_REGISTER_OUT_A 0x28
#define LSM9DS0_REGISTER_OUT_M 0x08
#define LSM9DS0_REGISTER_OUT_G 0x28
#define LSM9DS0_RESOLUTION_A (0.00006103515f) // scale/ADC tick -> 2g/0x8000
#define LSM9DS0_RESOLUTION_M (0.00006103515f) // scale/ADC tick -> 2G/0x8000
#define LSM9DS0_RESOLUTION_G (0.00747680664f) // scale/ADC tick -> 245DPS/0x8000

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
  p->accelerometer = read_accelerometer();
  p->magnetometer = read_magnetometer();
  p->gyroscope = read_gyroscope();
}

cJSON* convert_telemetry_packet_to_json(const telemetry_packet_t &p) {
  cJSON* root=cJSON_CreateObject();
  cJSON_AddStringToObject(root, "timestamp", p.timestamp);
  cJSON_AddNumberToObject(root, "rssi", p.rssi);
  cJSON_AddNumberToObject(root, "speed", p.speed);

  cJSON* accelerometer=cJSON_AddObjectToObject(root, "accelerometer");
  cJSON_AddNumberToObject(accelerometer, "x", p.accelerometer.x);
  cJSON_AddNumberToObject(accelerometer, "y", p.accelerometer.y);
  cJSON_AddNumberToObject(accelerometer, "z", p.accelerometer.z);

  cJSON* magnetometer=cJSON_AddObjectToObject(root, "magnetometer");
  cJSON_AddNumberToObject(magnetometer, "x", p.magnetometer.x);
  cJSON_AddNumberToObject(magnetometer, "y", p.magnetometer.y);
  cJSON_AddNumberToObject(magnetometer, "z", p.magnetometer.z);

  cJSON* gyroscope=cJSON_AddObjectToObject(root, "gyroscope");
  cJSON_AddNumberToObject(gyroscope, "x", p.gyroscope.x);
  cJSON_AddNumberToObject(gyroscope, "y", p.gyroscope.y);
  cJSON_AddNumberToObject(gyroscope, "z", p.gyroscope.z);

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

void i2c_init() {
  i2c_config_t conf = {};
  conf.mode = I2C_MODE_MASTER;
  conf.sda_io_num = 1;
  conf.scl_io_num = 2;
  conf.sda_pullup_en = GPIO_PULLUP_ENABLE;
  conf.scl_pullup_en = GPIO_PULLUP_ENABLE;
  conf.master.clk_speed = 400000;
  ESP_ERROR_CHECK(i2c_param_config(g_i2c_port, &conf));
  ESP_ERROR_CHECK(i2c_driver_install(g_i2c_port, conf.mode, 0, 0, 0));
}

void imu_read_register(uint8_t device_address, uint8_t reg_address, uint8_t* read_buf, size_t read_size) {
  uint8_t write_buf = reg_address | 0x80;  // Enable reading multiple bytes
  ESP_ERROR_CHECK(i2c_master_write_read_device(g_i2c_port, device_address, &write_buf, 1, read_buf, read_size, 1000 / portTICK_PERIOD_MS));
}

void imu_write_register(uint8_t device_address, uint8_t reg_address, uint8_t data) {
  uint8_t write_buf[2] = {reg_address, data};
  ESP_ERROR_CHECK(i2c_master_write_to_device(g_i2c_port, device_address, write_buf, sizeof(write_buf), 1000 / portTICK_PERIOD_MS));
}

void imu_init() {
  // I2C driver is installed by camera
  // i2c_init();

  uint8_t g_id = 0;
  imu_read_register(LSM9DS0_G_ADDRESS, LSM9DS0_REGISTER_WHO_AM_I_G, &g_id, 1);
  ESP_ERROR_CHECK(g_id == LSM9DS0_G_ID ? ESP_OK : ESP_FAIL);

  uint8_t xm_id = 0;
  imu_read_register(LSM9DS0_XM_ADDRESS, LSM9DS0_REGISTER_WHO_AM_I_XM, &xm_id, 1);
  ESP_ERROR_CHECK(xm_id == LSM9DS0_XM_ID ? ESP_OK : ESP_FAIL);

  imu_write_register(LSM9DS0_XM_ADDRESS, LSM9DS0_REGISTER_CTRL_REG1_XM, 0x67); // Accelerometer 100Hz data rate, x/y/z enabled

  imu_write_register(LSM9DS0_XM_ADDRESS, LSM9DS0_REGISTER_CTRL_REG5_XM, 0x94); // Magnetometer 100Hz data rate, temperature enabled
  imu_write_register(LSM9DS0_XM_ADDRESS, LSM9DS0_REGISTER_CTRL_REG6_XM, 0x00); // Magnetometer 2G scale
  imu_write_register(LSM9DS0_XM_ADDRESS, LSM9DS0_REGISTER_CTRL_REG7_XM, 0x00); // Magnetometer continuous-conversion mode

  imu_write_register(LSM9DS0_G_ADDRESS, LSM9DS0_REGISTER_CTRL_REG1_G, 0x0F); // Gyroscope normal mode, x/y/z enabled
}

vector3_t read_accelerometer() {
  uint8_t buf[6];
  imu_read_register(LSM9DS0_XM_ADDRESS, LSM9DS0_REGISTER_OUT_A, buf, sizeof(buf));

  int16_t raw_x = (buf[1] << 8) | buf[0];
  int16_t raw_y = (buf[3] << 8) | buf[2];
  int16_t raw_z = (buf[5] << 8) | buf[4];

  vector3_t out;
  out.x = (float)(raw_x) * LSM9DS0_RESOLUTION_A;
  out.y = (float)(raw_y) * LSM9DS0_RESOLUTION_A;
  out.z = (float)(raw_z) * LSM9DS0_RESOLUTION_A * -1;  // Module is mounted upside down
  return out;
}

vector3_t read_magnetometer() {
  uint8_t buf[6];
  imu_read_register(LSM9DS0_XM_ADDRESS, LSM9DS0_REGISTER_OUT_M, buf, sizeof(buf));

  int16_t raw_x = (buf[1] << 8) | buf[0];
  int16_t raw_y = (buf[3] << 8) | buf[2];
  int16_t raw_z = (buf[5] << 8) | buf[4];

  vector3_t out;
  out.x = (float)(raw_x) * LSM9DS0_RESOLUTION_M;
  out.y = (float)(raw_y) * LSM9DS0_RESOLUTION_M;
  out.z = (float)(raw_z) * LSM9DS0_RESOLUTION_M;
  return out;
}

vector3_t read_gyroscope() {
  uint8_t buf[6];
  imu_read_register(LSM9DS0_G_ADDRESS, LSM9DS0_REGISTER_OUT_G, buf, sizeof(buf));

  int16_t raw_x = (buf[1] << 8) | buf[0];
  int16_t raw_y = (buf[3] << 8) | buf[2];
  int16_t raw_z = (buf[5] << 8) | buf[4];

  vector3_t out;
  out.x = (float)(raw_x) * LSM9DS0_RESOLUTION_G;
  out.y = (float)(raw_y) * LSM9DS0_RESOLUTION_G;
  out.z = (float)(raw_z) * LSM9DS0_RESOLUTION_G;
  return out;
}

void telemetry_init() {
  sync_time();
  pcnt_init();
  imu_init();
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
