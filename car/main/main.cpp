// http://<IP>/?command=3&value=127

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_http_server.h"
#include "driver/gpio.h"
#include "nvs_flash.h"

#define WIFI_SSID "<SSID>"
#define WIFI_PASSWORD "<PASSWORD>"
#define WIFI_MAXIMUM_RETRY 2
#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT BIT1

#define COMMAND_START '1'
#define COMMAND_END '2'
#define COMMAND_TURN '3'
#define COMMAND_BRAKE '4'
#define COMMAND_ACCELERATE '5'

static char command = 0;
static int value = 0;

static const char* TAG = "car";
static EventGroupHandle_t s_wifi_event_group;
static int s_retry_num = 0;

static httpd_handle_t server = NULL;


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


static httpd_handle_t start_webserver()
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.lru_purge_enable = true;

    ESP_LOGI(TAG, "Starting server on port: '%d'", config.server_port);
    if (httpd_start(&server, &config) == ESP_OK) {
        ESP_LOGI(TAG, "Registering URI handlers");
        httpd_register_uri_handler(server, &root);
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


void setup()
{ 
  nvs_setup();
  wifi_setup();
  if (server == NULL) {
      ESP_LOGI(TAG, "Starting webserver");
      server = start_webserver();
  }
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
        break;
      case COMMAND_ACCELERATE:
        ESP_LOGI(TAG, "COMMAND_ACCELERATE: %d", value);
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
