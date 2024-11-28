#include "camera.hpp"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_camera.h"
#include "driver/i2c.h"
#include "esp_log.h"
#include "DFRobot_AXP313A.h"

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
};

void camera_init() {
  i2c_port_t i2c_master_port = I2C_NUM_0;

  i2c_config_t conf = {
      .mode = I2C_MODE_MASTER,
      .sda_io_num = 1,
      .scl_io_num = 2,
      .sda_pullup_en = GPIO_PULLUP_ENABLE,
      .scl_pullup_en = GPIO_PULLUP_ENABLE,
  };
  conf.master.clk_speed = 400000;
  i2c_param_config(i2c_master_port, &conf);
  i2c_driver_install(i2c_master_port, conf.mode, 0, 0, 0);

  begin(I2C_NUM_0, 0x36);
  enableCameraPower(OV2640);

  esp_err_t err = esp_camera_init(&camera_config);
  if (err != ESP_OK) {
    ESP_LOGI(TAG, "Camera init failed with error 0x%x", err);
    return;
  }
}

static QueueHandle_t g_frame_queue = NULL;
static TaskHandle_t g_camera_task_handle = NULL;

void camera_task(void* p) {
  camera_fb_t* frame = NULL;
  while (true) {
    // If queue is not processed then we get below warning:
    // cam_hal: Failed to get the frame on time!
    // camera_task should be resumed/suspended when web client connects/disconnects
    frame = esp_camera_fb_get();
    if (frame) {
      if (xQueueSendToBack(g_frame_queue, &frame, portMAX_DELAY) != pdPASS) {
        ESP_LOGE(TAG, "xQueueSendToBack failed");
        return;
      }
    }
  }
}

void camera_setup(QueueHandle_t frame_queue) {
  g_frame_queue = frame_queue;

  camera_init();

  if (xTaskCreate(camera_task, "camera_task", 4096, (void *)0, 5, &g_camera_task_handle) != pdPASS) {
    ESP_LOGE(TAG, "xTaskCreate(camera_task) failed");
    return;
  }
}
