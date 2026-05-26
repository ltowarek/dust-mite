#include "camera.hpp"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_camera.h"
#include "driver/i2c_master.h"
#include "esp_log.h"
#include "DFRobot_AXP313A.h"
#include "esp_opentelemetry.hpp"

static const char* TAG = "camera";

#define CAM_PIN_PWDN  -1
#define CAM_PIN_RESET -1
#define CAM_PIN_XCLK  45
#define CAM_PIN_SIOD  1
#define CAM_PIN_SIOC  2

#define CAM_PIN_D7    48
#define CAM_PIN_D6    46
#define CAM_PIN_D5    8
#define CAM_PIN_D4    7
#define CAM_PIN_D3    4
#define CAM_PIN_D2    41
#define CAM_PIN_D1    40
#define CAM_PIN_D0    39
#define CAM_PIN_VSYNC 6
#define CAM_PIN_HREF  42
#define CAM_PIN_PCLK  5

static camera_config_t camera_config = {
  .pin_pwdn = CAM_PIN_PWDN,
  .pin_reset = CAM_PIN_RESET,
  .pin_xclk = CAM_PIN_XCLK,
  .pin_sccb_sda = CAM_PIN_SIOD,
  .pin_sccb_scl = CAM_PIN_SIOC,

  .pin_d7 = CAM_PIN_D7,
  .pin_d6 = CAM_PIN_D6,
  .pin_d5 = CAM_PIN_D5,
  .pin_d4 = CAM_PIN_D4,
  .pin_d3 = CAM_PIN_D3,
  .pin_d2 = CAM_PIN_D2,
  .pin_d1 = CAM_PIN_D1,
  .pin_d0 = CAM_PIN_D0,
  .pin_vsync = CAM_PIN_VSYNC,
  .pin_href = CAM_PIN_HREF,
  .pin_pclk = CAM_PIN_PCLK,

  .xclk_freq_hz = 20000000,

  .ledc_timer = LEDC_TIMER_0,
  .ledc_channel = LEDC_CHANNEL_0,

  .pixel_format = PIXFORMAT_JPEG,
  .frame_size = FRAMESIZE_VGA,

  .jpeg_quality = 10,
  .fb_count = 2,
  .fb_location = CAMERA_FB_IN_PSRAM,
  .grab_mode = CAMERA_GRAB_LATEST,

  .sccb_i2c_port = 0,
};

void camera_init() {
  i2c_master_bus_config_t bus_cfg = {};
  bus_cfg.i2c_port = I2C_NUM_0;
  bus_cfg.sda_io_num = GPIO_NUM_1;
  bus_cfg.scl_io_num = GPIO_NUM_2;
  bus_cfg.clk_source = I2C_CLK_SRC_DEFAULT;
  bus_cfg.glitch_ignore_cnt = 7;
  bus_cfg.flags.enable_internal_pullup = true;

  i2c_master_bus_handle_t bus_handle;
  ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus_handle));

  begin(bus_handle, 0x36);
  enableCameraPower(OV2640);

  esp_err_t err = esp_camera_init(&camera_config);
  if (err != ESP_OK) {
    ESP_LOGI(TAG, "Camera init failed with error 0x%x", err);
    return;
  }
}

#define CAMERA_START_NOTIFICATION_INDEX 0
#define CAMERA_STOP_NOTIFICATION_INDEX 1

static QueueHandle_t g_frame_queue = NULL;
static TaskHandle_t g_camera_task_handle = NULL;

static bool has_jpeg_eoi(const camera_fb_t* frame) {
  return frame->len >= 2 &&
         frame->buf[frame->len - 2] == 0xFF &&
         frame->buf[frame->len - 1] == 0xD9;
}

void camera_task(void* p) {
  ESP_LOGI(TAG, "Starting camera task");
  camera_fb_t* frame = NULL;
  bool started = false;
  while (true) {
    if (!started) {
      ESP_LOGI(TAG, "Waiting for notification to start the camera");
      ulTaskNotifyTakeIndexed(CAMERA_START_NOTIFICATION_INDEX, pdTRUE, portMAX_DELAY);
      started = true;
      ESP_LOGI(TAG, "Camera started");
    }

    if (ulTaskNotifyTakeIndexed(CAMERA_STOP_NOTIFICATION_INDEX, pdTRUE, 0) == 1) {
      started = false;
      ESP_LOGI(TAG, "Camera stopped");
      continue;
    }

    frame = esp_camera_fb_get();
    if (!frame) {
      ESP_LOGW(TAG, "esp_camera_fb_get() returned NULL");
      vTaskDelay(pdMS_TO_TICKS(10));
      continue;
    }

    if (!has_jpeg_eoi(frame)) {
      ESP_LOGW(TAG, "NO-EOI detected (size=%zu)", frame->len);
      auto span = esp_opentelemetry_tracer()->StartSpan(
          "camera.frame.capture",
          {{"camera.frame.size", static_cast<int64_t>(frame->len)}});
      span->SetStatus(opentelemetry::trace::StatusCode::kError, "NO-EOI");
      span->End();
      esp_camera_fb_return(frame);
      continue;
    }

    if (xQueueSendToBack(g_frame_queue, &frame, portMAX_DELAY) != pdPASS) {
      ESP_LOGE(TAG, "xQueueSendToBack failed");
      break;
    }
  }
  ESP_LOGW(TAG, "Camera task stopped");
  vTaskDelete(NULL);
}

void camera_setup(QueueHandle_t frame_queue) {
  g_frame_queue = frame_queue;

  camera_init();

  if (xTaskCreate(camera_task, "camera_task", 4096, (void *)0, 5, &g_camera_task_handle) != pdPASS) {
    ESP_LOGE(TAG, "xTaskCreate(camera_task) failed");
    return;
  }
}

void camera_start() {
  xTaskNotifyGiveIndexed(g_camera_task_handle, CAMERA_START_NOTIFICATION_INDEX);
}

void camera_stop() {
  xTaskNotifyGiveIndexed(g_camera_task_handle, CAMERA_STOP_NOTIFICATION_INDEX);
}
