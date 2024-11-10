// http://<IP>/?command=3&value=127

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_camera.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_http_server.h"
#include "driver/gpio.h"
#include "driver/i2c.h"
#include "nvs_flash.h"
#include "DFRobot_AXP313A.h"
#include "driver/mcpwm.h"
#include "soc/mcpwm_struct.h" 
#include "soc/mcpwm_reg.h"

#ifndef WIFI_SSID
#define WIFI_SSID "<SSID>"
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "<PASSWORD>"
#endif

#define WIFI_MAXIMUM_RETRY 2
#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT BIT1

#define COMMAND_START '1'
#define COMMAND_END '2'
#define COMMAND_TURN '3'
#define COMMAND_BRAKE '4'
#define COMMAND_ACCELERATE '5'

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
  .frame_size = FRAMESIZE_UXGA,

  .jpeg_quality = 10,
  .fb_count = 2,
  .fb_location = CAMERA_FB_IN_PSRAM,
  .grab_mode = CAMERA_GRAB_LATEST,
};

static char command = 0;
static int value = 0;

static const char* TAG = "car";
static EventGroupHandle_t s_wifi_event_group;
static int s_retry_num = 0;

static httpd_handle_t server = NULL;

#define PART_BOUNDARY "123456789000000000000987654321"
static const char *_STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char *_STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char *_STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\nX-Timestamp: %d.%06d\r\n\r\n";

#define M1_IN1 12
#define M1_IN2 13
#define M2_IN1 14
#define M2_IN2 21
#define M3_IN1 9
#define M3_IN2 10
#define M4_IN1 47
#define M4_IN2 11

static esp_err_t root_get_handler(httpd_req_t *req)
{
  char*  buf;
  size_t buf_len;

  buf_len = httpd_req_get_url_query_len(req) + 1;
  if (buf_len > 1) {
      buf = (char*)malloc(buf_len);
      ESP_RETURN_ON_FALSE(buf, ESP_ERR_NO_MEM, TAG, "buffer alloc failed");
      if (httpd_req_get_url_query_str(req, buf, buf_len) == ESP_OK) {
          ESP_LOGI(TAG, "Found URL query => %s", buf);

          char command_param[2] = {0};
          if (httpd_query_key_value(buf, "command", command_param, sizeof(command_param)) == ESP_OK) {
              ESP_LOGI(TAG, "Found URL query parameter => command=%s", command_param);
              command = command_param[0];
              ESP_LOGI(TAG, "command=%c", command);
          }

          char value_param[5] = {0};
          if (httpd_query_key_value(buf, "value", value_param, sizeof(value_param)) == ESP_OK) {
              ESP_LOGI(TAG, "Found URL query parameter => value=%s", value_param);
              value = strtol(value_param, NULL, 0);
              ESP_LOGI(TAG, "value=%d", value);
          }
      }
      free(buf);
  }

  httpd_resp_set_status(req, HTTPD_200);
  httpd_resp_send(req, NULL, 0);

  return ESP_OK;
}


static const httpd_uri_t root = {
    .uri       = "/",
    .method    = HTTP_GET,
    .handler   = root_get_handler,
};


static esp_err_t stream_get_handler(httpd_req_t *req)
{
  esp_err_t res = ESP_OK;

  res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
  if (res) {
    return res;
  }
  res = httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  if (res) {
    return res;
  }
  res = httpd_resp_set_hdr(req, "X-Framerate", "60");
  if (res) {
    return res;
  }

  while (true) {
    camera_fb_t *frame = esp_camera_fb_get();

    res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
    if (res) {
      break;
    }

    char *part_buf[128];
    size_t hlen = snprintf((char *)part_buf, 128, _STREAM_PART, frame->len, frame->timestamp.tv_sec, frame->timestamp.tv_usec);
    res = httpd_resp_send_chunk(req, (const char *)part_buf, hlen);
    if (res) {
      break;
    }

    res = httpd_resp_send_chunk(req, (const char *)frame->buf, frame->len);
    if (res) {
      break;
    }

    esp_camera_fb_return(frame);
  }

  return res;
}


static const httpd_uri_t stream = {
    .uri       = "/stream",
    .method    = HTTP_GET,
    .handler   = stream_get_handler,
};


static httpd_handle_t start_webserver()
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.lru_purge_enable = true;

    ESP_LOGI(TAG, "Starting server on port: '%d'", config.server_port);
    if (httpd_start(&server, &config) == ESP_OK) {
        ESP_LOGI(TAG, "Registering URI handlers");
        httpd_register_uri_handler(server, &root);
        httpd_register_uri_handler(server, &stream);
        return server;
    }

    ESP_LOGI(TAG, "Error starting server!");
    return NULL;
}


static esp_err_t stop_webserver(httpd_handle_t server)
{
    return httpd_stop(server);
}


static void event_handler(void* arg, esp_event_base_t event_base,
                                int32_t event_id, void* event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
        httpd_handle_t* server = (httpd_handle_t*) arg;
        if (*server == NULL) {
            ESP_LOGI(TAG, "Starting webserver");
            *server = start_webserver();
        }
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        if (s_retry_num < WIFI_MAXIMUM_RETRY) {
            esp_wifi_connect();
            s_retry_num++;
            ESP_LOGI(TAG, "retry to connect to the AP");
        } else {
            xEventGroupSetBits(s_wifi_event_group, WIFI_FAIL_BIT);
        }
        ESP_LOGI(TAG, "connect to the AP fail");

        httpd_handle_t* server = (httpd_handle_t*) arg;
        if (*server) {
            ESP_LOGI(TAG, "Stopping webserver");
            if (stop_webserver(*server) == ESP_OK) {
                *server = NULL;
            } else {
                ESP_LOGE(TAG, "Failed to stop http server");
            }
        }
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t* event = (ip_event_got_ip_t*) event_data;
        ESP_LOGI(TAG, "got ip:" IPSTR, IP2STR(&event->ip_info.ip));
        s_retry_num = 0;
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}


void wifi_setup()
{
  s_wifi_event_group = xEventGroupCreate();
  ESP_ERROR_CHECK(esp_netif_init());

  ESP_ERROR_CHECK(esp_event_loop_create_default());
  esp_netif_create_default_wifi_sta();

  wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
  ESP_ERROR_CHECK(esp_wifi_init(&cfg));

  esp_event_handler_instance_t instance_any_id;
  esp_event_handler_instance_t instance_got_ip;
  ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT,
                                                      ESP_EVENT_ANY_ID,
                                                      &event_handler,
                                                      &server,
                                                      &instance_any_id));
  ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT,
                                                      IP_EVENT_STA_GOT_IP,
                                                      &event_handler,
                                                      &server,
                                                      &instance_got_ip));

  wifi_config_t wifi_config = {
    .sta = {
        .ssid = WIFI_SSID,
        .password = WIFI_PASSWORD
    }
  };
  ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
  ESP_ERROR_CHECK(esp_wifi_start());

  ESP_LOGI(TAG, "wifi_init_sta finished.");

  EventBits_t bits = xEventGroupWaitBits(
    s_wifi_event_group,
    WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
    pdFALSE,
    pdFALSE,
    portMAX_DELAY
  );

  if (bits & WIFI_CONNECTED_BIT) {
      ESP_LOGI(TAG, "connected to ap SSID:%s password:%s",
                wifi_config.sta.ssid, wifi_config.sta.password);
  } else if (bits & WIFI_FAIL_BIT) {
      ESP_LOGI(TAG, "Failed to connect to SSID:%s, password:%s",
                wifi_config.sta.ssid, wifi_config.sta.password);
  } else {
      ESP_LOGE(TAG, "UNEXPECTED EVENT");
  }
}


void nvs_setup() {
  esp_err_t ret = nvs_flash_init();
  if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    ESP_ERROR_CHECK(nvs_flash_erase());
    ret = nvs_flash_init();
  }
  ESP_ERROR_CHECK(ret);
}


void camera_setup() {
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


void motor_setup() {
  mcpwm_config_t pwm_config;
  pwm_config.frequency = 1000;
  pwm_config.cmpr_a = 0;
  pwm_config.cmpr_b = 0;
  pwm_config.counter_mode = MCPWM_UP_COUNTER;
  pwm_config.duty_mode = MCPWM_DUTY_MODE_0;

  mcpwm_gpio_init(MCPWM_UNIT_0,MCPWM0A,M1_IN1);
  mcpwm_gpio_init(MCPWM_UNIT_0,MCPWM0B,M1_IN2);
  mcpwm_init(MCPWM_UNIT_0,MCPWM_TIMER_0,&pwm_config);

  mcpwm_gpio_init(MCPWM_UNIT_0,MCPWM1A,M2_IN1);
  mcpwm_gpio_init(MCPWM_UNIT_0,MCPWM1B,M2_IN2);
  mcpwm_init(MCPWM_UNIT_0,MCPWM_TIMER_1,&pwm_config);

  mcpwm_gpio_init(MCPWM_UNIT_1,MCPWM0A,M3_IN1);
  mcpwm_gpio_init(MCPWM_UNIT_1,MCPWM0B,M3_IN2);
  mcpwm_init(MCPWM_UNIT_1,MCPWM_TIMER_0,&pwm_config);

  mcpwm_gpio_init(MCPWM_UNIT_1,MCPWM1A,M4_IN1);
  mcpwm_gpio_init(MCPWM_UNIT_1,MCPWM1B,M4_IN2);
  mcpwm_init(MCPWM_UNIT_1,MCPWM_TIMER_1,&pwm_config);
}


void accelerate(uint8_t speed)
{
  mcpwm_set_duty_type(MCPWM_UNIT_0,MCPWM_TIMER_0,MCPWM_GEN_A,MCPWM_DUTY_MODE_0);
  mcpwm_set_signal_low(MCPWM_UNIT_0,MCPWM_TIMER_0,MCPWM_GEN_B);
  mcpwm_set_duty(MCPWM_UNIT_0,MCPWM_TIMER_0,MCPWM_GEN_A,speed);

  mcpwm_set_duty_type(MCPWM_UNIT_0,MCPWM_TIMER_1,MCPWM_GEN_A,MCPWM_DUTY_MODE_0);
  mcpwm_set_signal_low(MCPWM_UNIT_0,MCPWM_TIMER_1,MCPWM_GEN_B);
  mcpwm_set_duty(MCPWM_UNIT_0,MCPWM_TIMER_1,MCPWM_GEN_A,speed);

  mcpwm_set_duty_type(MCPWM_UNIT_1,MCPWM_TIMER_0,MCPWM_GEN_A,MCPWM_DUTY_MODE_0);
  mcpwm_set_signal_low(MCPWM_UNIT_1,MCPWM_TIMER_0,MCPWM_GEN_B);
  mcpwm_set_duty(MCPWM_UNIT_1,MCPWM_TIMER_0,MCPWM_GEN_A,speed);

  mcpwm_set_duty_type(MCPWM_UNIT_1,MCPWM_TIMER_1,MCPWM_GEN_A,MCPWM_DUTY_MODE_0);
  mcpwm_set_signal_low(MCPWM_UNIT_1,MCPWM_TIMER_1,MCPWM_GEN_B);
  mcpwm_set_duty(MCPWM_UNIT_1,MCPWM_TIMER_1,MCPWM_GEN_A,speed);
}

void brake()
{
  mcpwm_set_signal_high(MCPWM_UNIT_0,MCPWM_TIMER_0,MCPWM_GEN_A);
  mcpwm_set_signal_high(MCPWM_UNIT_0,MCPWM_TIMER_0,MCPWM_GEN_B);

  mcpwm_set_signal_high(MCPWM_UNIT_0,MCPWM_TIMER_1,MCPWM_GEN_A);
  mcpwm_set_signal_high(MCPWM_UNIT_0,MCPWM_TIMER_1,MCPWM_GEN_B);

  mcpwm_set_signal_high(MCPWM_UNIT_1,MCPWM_TIMER_0,MCPWM_GEN_A);
  mcpwm_set_signal_high(MCPWM_UNIT_1,MCPWM_TIMER_0,MCPWM_GEN_B);

  mcpwm_set_signal_high(MCPWM_UNIT_1,MCPWM_TIMER_1,MCPWM_GEN_A);
  mcpwm_set_signal_high(MCPWM_UNIT_1,MCPWM_TIMER_1,MCPWM_GEN_B);
}


void setup()
{
  nvs_setup();
  wifi_setup();
  camera_setup();
  if (server == NULL) {
      ESP_LOGI(TAG, "Starting webserver");
      server = start_webserver();
  }
  motor_setup();
}


void loop()
{
  if (command != 0) {
    switch (command) {
      case COMMAND_START:
        ESP_LOGI(TAG, "COMMAND_START");
        break;
      case COMMAND_END:
        ESP_LOGI(TAG, "COMMAND_END");
        break;
      case COMMAND_TURN:
        ESP_LOGI(TAG, "COMMAND_TURN: %d", value);
        break;
      case COMMAND_BRAKE:
        ESP_LOGI(TAG, "COMMAND_BRAKE: %d", value);
        brake();
        break;
      case COMMAND_ACCELERATE:
        ESP_LOGI(TAG, "COMMAND_ACCELERATE: %d", value);
        // TODO: map value to proper range after motor/pwm calibration
        accelerate(60);
        break;
      default:
        ESP_LOGI(TAG, "Unknown command");
    }
    command = 0;
    value = 0;
  }

  vTaskDelay(10/portTICK_PERIOD_MS);
}


extern "C" void app_main()
{
  setup();
  while(true){
    loop();
  }
}
