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
#include "driver/i2c_master.h"
#include "driver/gpio.h"
#include "driver/mcpwm_cap.h"

static const char* TAG = "telemetry";

#define TELEMETRY_START_NOTIFICATION_INDEX 0
#define TELEMETRY_STOP_NOTIFICATION_INDEX 1
#define TELEMETRY_URM_ISR_INDEX 2

static QueueHandle_t g_telemetry_queue = NULL;
static TaskHandle_t g_telemetry_task_handle = NULL;
static TaskHandle_t g_urm_waiting_task = NULL;

static pcnt_unit_handle_t g_pcnt_unit = NULL;

static uint64_t g_previous_timestamp = 0;

static i2c_master_dev_handle_t g_imu_xm_dev = NULL;
static i2c_master_dev_handle_t g_imu_g_dev  = NULL;

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

#define URM_ECHO_PIN GPIO_NUM_17
#define URM_TRIG_PIN GPIO_NUM_16

void sync_time() {
  ESP_LOGI(TAG, "Initializing SNTP");
  esp_sntp_config_t config = ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org");
  esp_netif_sntp_init(&config);

  while (esp_netif_sntp_sync_wait(2000 / portTICK_PERIOD_MS) == ESP_ERR_TIMEOUT) {
    ESP_LOGI(TAG, "Waiting for system time to be set...");
  }
  ESP_LOGI(TAG, "Set system time");
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
  p->distance_ahead = get_distance_ahead();
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
  return velocity_kph;
}

static i2c_master_dev_handle_t imu_dev_handle(uint8_t device_address) {
  if (device_address == LSM9DS0_XM_ADDRESS) return g_imu_xm_dev;
  if (device_address == LSM9DS0_G_ADDRESS)  return g_imu_g_dev;
  return NULL;
}

void imu_read_register(uint8_t device_address, uint8_t reg_address, uint8_t* read_buf, size_t read_size) {
  i2c_master_dev_handle_t dev = imu_dev_handle(device_address);
  if (!dev) return;
  uint8_t write_buf = reg_address | 0x80;  // Enable reading multiple bytes
  ESP_ERROR_CHECK(i2c_master_transmit_receive(dev, &write_buf, 1, read_buf, read_size, 1000));
}

void imu_write_register(uint8_t device_address, uint8_t reg_address, uint8_t data) {
  i2c_master_dev_handle_t dev = imu_dev_handle(device_address);
  if (!dev) return;
  uint8_t write_buf[2] = {reg_address, data};
  ESP_ERROR_CHECK(i2c_master_transmit(dev, write_buf, sizeof(write_buf), 1000));
}

void imu_init(i2c_master_bus_handle_t bus_handle) {
  i2c_device_config_t dev_cfg = {};
  dev_cfg.dev_addr_length = I2C_ADDR_BIT_LEN_7;
  dev_cfg.scl_speed_hz = 400000;

  dev_cfg.device_address = LSM9DS0_XM_ADDRESS;
  ESP_ERROR_CHECK(i2c_master_bus_add_device(bus_handle, &dev_cfg, &g_imu_xm_dev));

  dev_cfg.device_address = LSM9DS0_G_ADDRESS;
  ESP_ERROR_CHECK(i2c_master_bus_add_device(bus_handle, &dev_cfg, &g_imu_g_dev));

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

static uint32_t g_cap_resolution_hz = 0;
static mcpwm_cap_channel_handle_t g_cap_channel = NULL;

static bool urm_echo_isr_handler(mcpwm_cap_channel_handle_t cap_channel, const mcpwm_capture_event_data_t *edata, void *user_data) {
  static uint32_t begin_of_sample = 0;
  static uint32_t end_of_sample = 0;

  BaseType_t high_task_wakeup = pdFALSE;
  if (edata->cap_edge == MCPWM_CAP_EDGE_NEG) {
    begin_of_sample = edata->cap_value;
    end_of_sample = begin_of_sample;
  } else {
    end_of_sample = edata->cap_value;
    uint32_t pulse_count = end_of_sample - begin_of_sample;
    if (g_urm_waiting_task != NULL) {
      xTaskNotifyIndexedFromISR(g_urm_waiting_task, TELEMETRY_URM_ISR_INDEX, pulse_count, eSetValueWithOverwrite, &high_task_wakeup);
    }
  }
  return high_task_wakeup == pdTRUE;
}

void urm_init() {
  ESP_ERROR_CHECK(gpio_set_direction(URM_TRIG_PIN, GPIO_MODE_OUTPUT));
  ESP_ERROR_CHECK(gpio_pulldown_en(URM_TRIG_PIN));
  ESP_ERROR_CHECK(gpio_set_level(URM_TRIG_PIN, 1));

  mcpwm_cap_timer_handle_t cap_timer = NULL;
  mcpwm_capture_timer_config_t cap_timer_cfg = {};
  cap_timer_cfg.group_id = 0;
  cap_timer_cfg.clk_src = MCPWM_CAPTURE_CLK_SRC_DEFAULT;
  ESP_ERROR_CHECK(mcpwm_new_capture_timer(&cap_timer_cfg, &cap_timer));
  ESP_ERROR_CHECK(mcpwm_capture_timer_get_resolution(cap_timer, &g_cap_resolution_hz));

  mcpwm_capture_channel_config_t cap_ch_cfg = {};
  cap_ch_cfg.gpio_num = URM_ECHO_PIN;
  cap_ch_cfg.prescale = 1;
  cap_ch_cfg.flags.neg_edge = true;
  cap_ch_cfg.flags.pos_edge = true;
  ESP_ERROR_CHECK(mcpwm_new_capture_channel(cap_timer, &cap_ch_cfg, &g_cap_channel));

  mcpwm_capture_event_callbacks_t cbs = {};
  cbs.on_cap = urm_echo_isr_handler;
  ESP_ERROR_CHECK(mcpwm_capture_channel_register_event_callbacks(g_cap_channel, &cbs, NULL));
  ESP_ERROR_CHECK(mcpwm_capture_channel_enable(g_cap_channel));
  ESP_ERROR_CHECK(mcpwm_capture_timer_enable(cap_timer));
  ESP_ERROR_CHECK(mcpwm_capture_timer_start(cap_timer));

  // ESP-IDF v6 no longer configures GPIO pulls inside mcpwm_new_capture_channel
  // (commit cb097aeb54 removed gpio_config() call). Without an explicit pull-up
  // on the active-LOW echo pin, the floating input picks up trigger-pulse EMI and
  // fires rapid NEG+POS pairs yielding near-zero pulse widths (distance_ahead=0).
  // The HC-SR04 example in v6 likewise requires gpio_set_pull_mode(GPIO_PULLUP_ONLY).
  gpio_pullup_en(URM_ECHO_PIN);
  gpio_pulldown_dis(URM_ECHO_PIN);
}

int get_distance_ahead() {
  g_urm_waiting_task = xTaskGetCurrentTaskHandle();
  xTaskNotifyStateClearIndexed(NULL, TELEMETRY_URM_ISR_INDEX);
  ESP_ERROR_CHECK(gpio_set_level(URM_TRIG_PIN, 0));
  esp_rom_delay_us(10);
  ESP_ERROR_CHECK(gpio_set_level(URM_TRIG_PIN, 1));

  uint32_t pulse_count = 0;
  bool notified = xTaskNotifyWaitIndexed(TELEMETRY_URM_ISR_INDEX, 0x00, ULONG_MAX, &pulse_count, pdMS_TO_TICKS(1000)) == pdTRUE;
  g_urm_waiting_task = NULL;

  if (notified) {
    uint32_t pulse_width_us = (uint32_t)((uint64_t)pulse_count * 1000000ULL / g_cap_resolution_hz);
    if (pulse_width_us >= 50000) {
      ESP_LOGW(TAG, "Invalid URM pulse width");
      return -1;
    }

    float distance_cm = (float)pulse_width_us / 50;
    return (int)distance_cm;
  }
  ESP_LOGW(TAG, "URM callback timeout");
  return -1;
}

void telemetry_init(i2c_master_bus_handle_t i2c_bus) {
  pcnt_init();
  imu_init(i2c_bus);
  urm_init();
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

void telemetry_setup(QueueHandle_t telemetry_queue, i2c_master_bus_handle_t i2c_bus) {
  g_telemetry_queue = telemetry_queue;

  telemetry_init(i2c_bus);

  if (xTaskCreate(telemetry_task, "telemetry_task", 4096, (void *)0, 1, &g_telemetry_task_handle) != pdPASS) {
    ESP_LOGE(TAG, "xTaskCreate(telemetry_task) failed");
    return;
  }
}

void telemetry_start() {
  if (!g_telemetry_task_handle) {
    ESP_LOGE(TAG, "telemetry_start called before telemetry_setup");
    return;
  }
  xTaskNotifyGiveIndexed(g_telemetry_task_handle, TELEMETRY_START_NOTIFICATION_INDEX);
}

void telemetry_stop() {
  if (!g_telemetry_task_handle) {
    ESP_LOGE(TAG, "telemetry_stop called before telemetry_setup");
    return;
  }
  xTaskNotifyGiveIndexed(g_telemetry_task_handle, TELEMETRY_STOP_NOTIFICATION_INDEX);
}
