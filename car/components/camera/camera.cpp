#include "camera.hpp"
#include "camera_metrics.hpp"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_camera.h"
#include "driver/i2c_master.h"
#include "esp_log.h"
#include "DFRobot_AXP313A.h"

static const char* TAG = "camera";

#define CAM_PIN_PWDN  -1
#define CAM_PIN_RESET -1
#define CAM_PIN_XCLK  45

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
  .pin_sccb_sda = -1,
  .pin_sccb_scl = -1,

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

  // Lower number = higher quality / larger JPEGs.
  .jpeg_quality = 10,
  .fb_count = 2,
  .fb_location = CAMERA_FB_IN_PSRAM,
  .grab_mode = CAMERA_GRAB_LATEST,

  .sccb_i2c_port = 0,
};

void camera_init(i2c_master_bus_handle_t i2c_bus) {
  begin(i2c_bus, 0x36);
  enableCameraPower(OV2640);
}

#define CAMERA_START_NOTIFICATION_INDEX 0
#define CAMERA_STOP_NOTIFICATION_INDEX 1

static QueueHandle_t g_frame_queue = NULL;
static TaskHandle_t g_camera_task_handle = NULL;

void camera_task(void* p) {
  ESP_LOGI(TAG, "Starting camera task");
  camera_fb_t* frame = NULL;
  bool started = false;
  bool initialized = false;
  while (true) {
    if (!started) {
      ESP_LOGI(TAG, "Waiting for notification to start the camera");
      ulTaskNotifyTakeIndexed(CAMERA_START_NOTIFICATION_INDEX, pdTRUE, portMAX_DELAY);
      if (!initialized) {
        // Lazy init on the first stream request so the sensor stays quiet
        // while idle. esp_camera_init() drops one or two unaligned warmup
        // frames ("cam_hal: NO-SOI") before locking - this is benign and
        // self-recovers on the next VSYNC.
        esp_err_t err = esp_camera_init(&camera_config);
        if (err != ESP_OK) {
          ESP_LOGE(TAG, "esp_camera_init failed: 0x%x", err);
          continue;  // wait for the next stream request and retry
        }
        initialized = true;
      }
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

    camera_metrics_update(frame->len);

    if (xQueueSendToBack(g_frame_queue, &frame, portMAX_DELAY) != pdPASS) {
      ESP_LOGE(TAG, "xQueueSendToBack failed");
      break;
    }
  }
  ESP_LOGW(TAG, "Camera task stopped");
  vTaskDelete(NULL);
}

void camera_setup(QueueHandle_t frame_queue, i2c_master_bus_handle_t i2c_bus) {
  g_frame_queue = frame_queue;

  camera_init(i2c_bus);

  if (xTaskCreate(camera_task, "camera_task", 4096, (void *)0, 5, &g_camera_task_handle) != pdPASS) {
    ESP_LOGE(TAG, "xTaskCreate(camera_task) failed");
    return;
  }
}

void camera_start() {
  if (!g_camera_task_handle) {
    ESP_LOGE(TAG, "camera_start called before camera_setup");
    return;
  }
  xTaskNotifyGiveIndexed(g_camera_task_handle, CAMERA_START_NOTIFICATION_INDEX);
}

void camera_stop() {
  if (!g_camera_task_handle) {
    ESP_LOGE(TAG, "camera_stop called before camera_setup");
    return;
  }
  xTaskNotifyGiveIndexed(g_camera_task_handle, CAMERA_STOP_NOTIFICATION_INDEX);
}
