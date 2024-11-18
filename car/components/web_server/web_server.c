#include <stdio.h>
#include "esp_check.h"
#include "esp_log.h"
#include "web_server.h"
#include "esp_http_server.h"
#include "esp_wifi.h"
#include "nvs_flash.h"
#include <cJSON.h>

static const char* TAG = "web_server";

#ifndef WIFI_SSID
#define WIFI_SSID "<SSID>"
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "<PASSWORD>"
#endif

#define WIFI_MAXIMUM_RETRY 2
#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT BIT1

static EventGroupHandle_t s_wifi_event_group;
static int s_retry_num = 0;

static httpd_handle_t server = NULL;

#define PART_BOUNDARY "123456789000000000000987654321"
static const char *_STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char *_STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char *_STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

void (*g_command_handler)(char, int*) = NULL;
frame_t* (*g_frame_get_handler)() = NULL;
void (*g_frame_return_handler)(frame_t*) = NULL;

void register_command_handler(void (*handler)(char, int*)) {
  g_command_handler = handler;
}

void register_frame_get_handler(frame_t* (*handler)()) {
  g_frame_get_handler = handler;
}

void register_frame_return_handler(void (*handler)(frame_t*)) {
  g_frame_return_handler = handler;
}

static esp_err_t root_get_handler(httpd_req_t *req) {
  esp_err_t ret = ESP_OK;

  if (req->method == HTTP_GET) {
    ESP_LOGI(TAG, "Handshake done, the new connection was opened");
    return ESP_OK;
  }

  httpd_ws_frame_t ws_pkt = {0};

  ret = httpd_ws_recv_frame(req, &ws_pkt, 0);
  if (ret != ESP_OK) {
    ESP_LOGE(TAG, "httpd_ws_recv_frame failed to get frame len with %d", ret);
    return ret;
  }
  ESP_LOGI(TAG, "frame len is %d", ws_pkt.len);

  if (ws_pkt.type != HTTPD_WS_TYPE_TEXT) {
    ESP_LOGE(TAG, "Invalid packet type: %d", ws_pkt.type);
    return ESP_FAIL;
  }

  unsigned char *buf = NULL;
  if (ws_pkt.len > 0) {
    buf = malloc(ws_pkt.len + 1);
    buf[ws_pkt.len] = '\0';
  }

  ws_pkt.payload = buf;
  ret = httpd_ws_recv_frame(req, &ws_pkt, ws_pkt.len);
  if (ret != ESP_OK) {
    ESP_LOGE(TAG, "httpd_ws_recv_frame failed with %d", ret);
    free(buf);
    return ret;
  }

  cJSON *root = cJSON_Parse((const char*)ws_pkt.payload);
  if (root) {
      cJSON *command_obj = cJSON_GetObjectItem(root, "command");
      cJSON *value_obj = cJSON_GetObjectItem(root, "value");
      char command = (char)cJSON_GetNumberValue(command_obj);
      int value = (int)cJSON_GetNumberValue(value_obj);
      ESP_LOGI(TAG, "JSON={\"command\": %d, \"value\": %d}", command, value);
      cJSON_Delete(root);

      int* value_ptr = (value == 2147483647) ? NULL : &value;
      g_command_handler(command, value_ptr);
  } else {
    ESP_LOGW(TAG, "Failed to parse JSON: %s", ws_pkt.payload);
  }

  free(buf);
  return ret;
}

static const httpd_uri_t root = {
    .uri       = "/",
    .method    = HTTP_GET,
    .handler   = root_get_handler,
    .is_websocket = true
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
    frame_t *frame = g_frame_get_handler();

    res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
    if (res) {
      break;
    }

    char *part_buf[128];
    size_t hlen = snprintf((char *)part_buf, 128, _STREAM_PART, frame->len);
    res = httpd_resp_send_chunk(req, (const char *)part_buf, hlen);
    if (res) {
      break;
    }

    res = httpd_resp_send_chunk(req, (const char *)frame->buf, frame->len);
    if (res) {
      break;
    }

    g_frame_return_handler(frame);
  }

  return res;
}


static const httpd_uri_t stream = {
    .uri       = "/stream",
    .method    = HTTP_GET,
    .handler   = stream_get_handler,
};


static httpd_handle_t start_web_server()
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


static esp_err_t stop_web_server(httpd_handle_t server)
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
            ESP_LOGI(TAG, "Starting web_server");
            *server = start_web_server();
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
            ESP_LOGI(TAG, "Stopping web_server");
            if (stop_web_server(*server) == ESP_OK) {
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


void nvs_setup(void) {
  esp_err_t ret = nvs_flash_init();
  if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    ESP_ERROR_CHECK(nvs_flash_erase());
    ret = nvs_flash_init();
  }
  ESP_ERROR_CHECK(ret);
}


void wifi_setup()
{
  nvs_setup();

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
