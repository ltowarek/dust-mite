#include "web_server.hpp"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include <stdio.h>
#include "esp_err.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_camera.h"
#include "esp_http_server.h"
#include "esp_wifi.h"
#include "esp_camera.h"
#include "nvs_flash.h"
#include "motor.hpp"
#include <cJSON.h>

static const char* TAG = "web_server";

#ifndef WIFI_SSID
#define WIFI_SSID "<SSID>"
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "<PASSWORD>"
#endif

#define MAX_ASYNC_REQUESTS 1

static httpd_handle_t server = NULL;

static QueueHandle_t g_frame_queue = NULL;
static QueueHandle_t g_command_queue = NULL;

static QueueHandle_t g_async_req_queue = NULL;
static SemaphoreHandle_t g_worker_ready_count = NULL;
static TaskHandle_t g_worker_handles[MAX_ASYNC_REQUESTS];

typedef esp_err_t (*httpd_req_handler_t)(httpd_req_t *req);

typedef struct {
  httpd_req_t* req;
  httpd_req_handler_t handler;
} httpd_async_req_t;

static bool is_on_async_worker_thread(void)
{
    TaskHandle_t handle = xTaskGetCurrentTaskHandle();
    for (int i = 0; i < MAX_ASYNC_REQUESTS; i++) {
        if (g_worker_handles[i] == handle) {
            return true;
        }
    }
    return false;
}

static esp_err_t submit_async_req(httpd_req_t *req, httpd_req_handler_t handler)
{
  httpd_req_t* copy = NULL;
  ESP_ERROR_CHECK(httpd_req_async_handler_begin(req, &copy));

  httpd_async_req_t async_req = {
    .req = copy,
    .handler = handler,
  };

  if (xSemaphoreTake(g_worker_ready_count, 0) == false) {
    ESP_LOGE(TAG, "No workers are available");
    httpd_req_async_handler_complete(copy);
    return ESP_FAIL;
  }

  if (xQueueSendToBack(g_async_req_queue, &async_req, pdMS_TO_TICKS(100)) != pdPASS) {
    ESP_LOGE(TAG, "worker queue is full");
    httpd_req_async_handler_complete(copy);
    return ESP_FAIL;
  }

  return ESP_OK;
}

static esp_err_t root_get_handler(httpd_req_t *req) {
  esp_err_t ret = ESP_OK;

  if (req->method == HTTP_GET) {
    ESP_LOGI(TAG, "Handshake done, the new connection was opened");
    return ESP_OK;
  }

  httpd_ws_frame_t ws_pkt = {};
  ESP_ERROR_CHECK(httpd_ws_recv_frame(req, &ws_pkt, 0));
  ESP_LOGI(TAG, "frame len is %d", ws_pkt.len);

  if (ws_pkt.type != HTTPD_WS_TYPE_TEXT) {
    ESP_LOGE(TAG, "Invalid packet type: %d", ws_pkt.type);
    return ESP_FAIL;
  }

  unsigned char *buf = NULL;
  if (ws_pkt.len > 0) {
    buf = (unsigned char *)malloc(ws_pkt.len + 1);
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

      command_packet_t packet = {
        .command = command,
        .value = value,
      };
      if (xQueueSendToBack(g_command_queue, &packet, portMAX_DELAY) != pdPASS) {
        ESP_LOGE(TAG, "xQueueSendToBack failed");
        return ESP_FAIL;
      }
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
    .user_ctx  = NULL,
    .is_websocket = true,
    .handle_ws_control_frames = false,
    .supported_subprotocol = NULL
};

static esp_err_t stream_get_handler(httpd_req_t *req)
{
  esp_err_t ret = ESP_OK;

  if (is_on_async_worker_thread() == false) {
    if (submit_async_req(req, stream_get_handler) == ESP_OK) {
        return ret;
    } else {
        httpd_resp_set_status(req, "503 Busy");
        httpd_resp_sendstr(req, "<div> no workers available. server busy.</div>");
        return ret;
    }
  }

  if (req->method == HTTP_GET) {
    ESP_LOGI(TAG, "Handshake done, the new connection was opened");
  }

  camera_fb_t* frame = NULL;
  while (true) {
    if (xQueueReceive(g_frame_queue, &frame, portMAX_DELAY) != pdPASS) {
      ESP_LOGE(TAG, "xQueueReceive failed");
      return ESP_FAIL;
    }

    httpd_ws_frame_t ws_pkt = {};
    ws_pkt.type = HTTPD_WS_TYPE_BINARY;
    ws_pkt.payload = frame->buf;
    ws_pkt.len = frame->len;

    ret = httpd_ws_send_frame(req, &ws_pkt);
    if (ret != ESP_OK) {
      ESP_LOGE(TAG, "httpd_ws_send_frame failed with %d", ret);
      esp_camera_fb_return(frame);
      return ret;
    }

    esp_camera_fb_return(frame);
  }

  return ret;
}

static const httpd_uri_t stream = {
    .uri       = "/stream",
    .method    = HTTP_GET,
    .handler   = stream_get_handler,
    .user_ctx  = NULL,
    .is_websocket = true,
    .handle_ws_control_frames = false,
    .supported_subprotocol = NULL
};

static httpd_handle_t start_web_server()
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.lru_purge_enable = true;
    config.max_open_sockets = MAX_ASYNC_REQUESTS + 1;

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

static void async_req_worker_task(void *p)
{
  ESP_LOGI(TAG, "starting async req task worker");
  while (true) {
    xSemaphoreGive(g_worker_ready_count);

    httpd_async_req_t async_req;
    if (xQueueReceive(g_async_req_queue, &async_req, portMAX_DELAY)) {
      ESP_LOGI(TAG, "invoking %s", async_req.req->uri);
      async_req.handler(async_req.req);
      if (httpd_req_async_handler_complete(async_req.req) != ESP_OK) {
        ESP_LOGE(TAG, "failed to complete async req");
      }
    }
  }
  ESP_LOGW(TAG, "worker stopped");
  vTaskDelete(NULL);
}

static void start_async_req_workers(void)
{
  g_worker_ready_count = xSemaphoreCreateCounting(MAX_ASYNC_REQUESTS, 0);
  if (g_worker_ready_count == NULL) {
    ESP_LOGE(TAG, "Failed to create workers counting Semaphore");
    return;
  }

  g_async_req_queue = xQueueCreate(1, sizeof(httpd_async_req_t));
  if (g_async_req_queue == NULL){
    ESP_LOGE(TAG, "Failed to create g_async_req_queue");
    vSemaphoreDelete(g_worker_ready_count);
    return;
  }

  for (int i = 0; i < MAX_ASYNC_REQUESTS; i++) {
    if (xTaskCreate(async_req_worker_task, "async_req_worker", 4096, (void*)0, 1, &g_worker_handles[i]) != pdPASS) {
      ESP_LOGE(TAG, "Failed to start async_req_worker_task");
      continue;
    }
  }
}

static void web_server_handler_on_got_ip(void* arg, esp_event_base_t event_base,
                            int32_t event_id, void* event_data)
{
    httpd_handle_t* server = (httpd_handle_t*) arg;
    if (*server == NULL) {
        ESP_LOGI(TAG, "Starting web server");
        *server = start_web_server();
    }
}

static void web_server_handler_on_wifi_disconnect(void* arg, esp_event_base_t event_base,
                               int32_t event_id, void* event_data)
{
    httpd_handle_t* server = (httpd_handle_t*) arg;
    if (*server) {
        ESP_LOGI(TAG, "Stopping web server");
        if (stop_web_server(*server) == ESP_OK) {
            *server = NULL;
        } else {
            ESP_LOGE(TAG, "Failed to stop http server");
        }
    }
}

void web_server_setup(QueueHandle_t frame_queue, QueueHandle_t command_queue) {
  g_frame_queue = frame_queue;
  g_command_queue = command_queue;

  start_async_req_workers();

  ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &web_server_handler_on_got_ip, &server));
  ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED, &web_server_handler_on_wifi_disconnect, &server));

  start_web_server();
}

void wifi_setup()
{
  ESP_ERROR_CHECK(nvs_flash_init());
  ESP_ERROR_CHECK(esp_netif_init());
  ESP_ERROR_CHECK(esp_event_loop_create_default());
  esp_netif_create_default_wifi_sta();

  wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
  ESP_ERROR_CHECK(esp_wifi_init(&cfg));

  wifi_config_t wifi_config = {};
  strcpy((char*)wifi_config.sta.ssid, WIFI_SSID);
  strcpy((char*)wifi_config.sta.password, WIFI_PASSWORD);
  ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
  ESP_ERROR_CHECK(esp_wifi_start());
  ESP_ERROR_CHECK(esp_wifi_connect());

  ESP_LOGI(TAG, "wifi_init_sta finished.");
}
