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
#include "camera.hpp"
#include "telemetry.hpp"
#include <cJSON.h>

static const char* TAG = "web_server";

#ifndef WIFI_SSID
#define WIFI_SSID "<SSID>"
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "<PASSWORD>"
#endif

#define CAMERA_STOPPED_NOTIFICATION_INDEX 0
#define TELEMETRY_STOPPED_NOTIFICATION_INDEX 1

static httpd_handle_t server = NULL;
static TaskHandle_t g_server_task_handle = NULL;

static QueueHandle_t g_command_queue = NULL;

static QueueHandle_t g_frame_queue = NULL;
static QueueHandle_t g_stream_req_queue = NULL;
static TaskHandle_t g_stream_task_handle = NULL;

static QueueHandle_t g_telemetry_packet_queue = NULL;
static QueueHandle_t g_telemetry_req_queue = NULL;
static TaskHandle_t g_telemetry_task_handle = NULL;

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

static esp_err_t stream_handle_handshake(httpd_req_t *req) {
  ESP_LOGI(TAG, "Handshake done, the new connection was opened");
  httpd_req_t* copy = NULL;
  ESP_ERROR_CHECK(httpd_req_async_handler_begin(req, &copy));
  if (xQueueSendToBack(g_stream_req_queue, &copy, portMAX_DELAY) != pdPASS) {
    ESP_LOGE(TAG, "xQueueSendToBack(g_stream_req_queue) failed");
    return ESP_FAIL;
  }
  return ESP_OK;
}

static esp_err_t stream_handle_websocket_frame(httpd_req_t *req) {
  esp_err_t ret = ESP_OK;

  httpd_ws_frame_t ws_pkt = {};
  ESP_ERROR_CHECK(httpd_ws_recv_frame(req, &ws_pkt, 0));

  unsigned char *buf = NULL;
  if (ws_pkt.len > 0) {
    buf = (unsigned char *)malloc(ws_pkt.len);
  }

  ws_pkt.payload = buf;
  ret = httpd_ws_recv_frame(req, &ws_pkt, ws_pkt.len);
  if (ret != ESP_OK) {
    ESP_LOGE(TAG, "httpd_ws_recv_frame failed with %d", ret);
    free(buf);
    return ret;
  }

  if (ws_pkt.type == HTTPD_WS_TYPE_PING || ws_pkt.type == HTTPD_WS_TYPE_CLOSE) {
    if (ws_pkt.type == HTTPD_WS_TYPE_PING) {
      ESP_LOGI(TAG, "Got a WS PING frame, Replying PONG");
      ws_pkt.type = HTTPD_WS_TYPE_PONG;
    } else if (ws_pkt.type == HTTPD_WS_TYPE_CLOSE) {
      ESP_LOGI(TAG, "Got a WS CLOSE frame, Replying CLOSE");
      ws_pkt.len = 0;
      ws_pkt.payload = NULL;
      xTaskNotifyGive(g_stream_task_handle);
      ulTaskNotifyTakeIndexed(CAMERA_STOPPED_NOTIFICATION_INDEX, pdTRUE, portMAX_DELAY);
    }

    ESP_LOGI(TAG, "Sending control frame from stream handler");
    ret = httpd_ws_send_frame(req, &ws_pkt);
    if (ret != ESP_OK) {
      ESP_LOGE(TAG, "httpd_ws_send_frame failed with %d", ret);
      free(buf);
      return ret;
    }
  }

  free(buf);
  return ret;
}

static esp_err_t stream_get_handler(httpd_req_t *req)
{
  if (g_server_task_handle == NULL) {
    g_server_task_handle = xTaskGetCurrentTaskHandle();
  }

  if (req->method == HTTP_GET) {
    ESP_ERROR_CHECK(stream_handle_handshake(req));
  } else {
    ESP_ERROR_CHECK(stream_handle_websocket_frame(req));
  }

  return ESP_OK;
}

void ws_stream_task(void* p) {
  ESP_LOGI(TAG, "Starting stream task");
  esp_err_t ret = ESP_OK;
  httpd_req_t* req = NULL;
  camera_fb_t* frame = NULL;
  while (true) {
    if (req == NULL) {
      ESP_LOGI(TAG, "Waiting for notification to start the stream");
      if (xQueueReceive(g_stream_req_queue, &req, portMAX_DELAY) != pdPASS) {
        ESP_LOGE(TAG, "xQueueReceive(g_stream_req_queue) failed");
        break;
      }
      camera_start();
      ESP_LOGI(TAG, "Stream started");
    }

    if (xQueueReceive(g_frame_queue, &frame, portMAX_DELAY) != pdPASS) {
      ESP_LOGE(TAG, "xQueueReceive(g_frame_queue) failed");
      break;
    }

    if (ulTaskNotifyTake(pdTRUE, 0) == 1) {
      esp_camera_fb_return(frame);
      if (httpd_req_async_handler_complete(req) != ESP_OK) {
        ESP_LOGE(TAG, "failed to complete async stream req");
      }
      req = NULL;
      camera_stop();
      ESP_LOGI(TAG, "Stream stopped");
      xTaskNotifyGiveIndexed(g_server_task_handle, CAMERA_STOPPED_NOTIFICATION_INDEX);
      continue;
    }

    httpd_ws_frame_t ws_pkt = {};
    ws_pkt.type = HTTPD_WS_TYPE_BINARY;
    ws_pkt.payload = frame->buf;
    ws_pkt.len = frame->len;

    ret = httpd_ws_send_frame(req, &ws_pkt);
    if (ret != ESP_OK) {
      ESP_LOGE(TAG, "httpd_ws_send_frame failed with %d", ret);
      esp_camera_fb_return(frame);
      break;
    }

    esp_camera_fb_return(frame);
  }
  ESP_LOGW(TAG, "Stream task stopped");
  vTaskDelete(NULL);
}

static const httpd_uri_t stream = {
    .uri       = "/stream",
    .method    = HTTP_GET,
    .handler   = stream_get_handler,
    .user_ctx  = NULL,
    .is_websocket = true,
    .handle_ws_control_frames = true,
    .supported_subprotocol = NULL
};

static esp_err_t telemetry_handle_handshake(httpd_req_t *req) {
  ESP_LOGI(TAG, "Handshake done, the new connection was opened");
  httpd_req_t* copy = NULL;
  ESP_ERROR_CHECK(httpd_req_async_handler_begin(req, &copy));
  if (xQueueSendToBack(g_telemetry_req_queue, &copy, portMAX_DELAY) != pdPASS) {
    ESP_LOGE(TAG, "xQueueSendToBack(g_telemetry_req_queue) failed");
    return ESP_FAIL;
  }
  return ESP_OK;
}

static esp_err_t telemetry_handle_websocket_frame(httpd_req_t *req) {
  esp_err_t ret = ESP_OK;

  httpd_ws_frame_t ws_pkt = {};
  ESP_ERROR_CHECK(httpd_ws_recv_frame(req, &ws_pkt, 0));

  unsigned char *buf = NULL;
  if (ws_pkt.len > 0) {
    buf = (unsigned char *)malloc(ws_pkt.len);
  }

  ws_pkt.payload = buf;
  ret = httpd_ws_recv_frame(req, &ws_pkt, ws_pkt.len);
  if (ret != ESP_OK) {
    ESP_LOGE(TAG, "httpd_ws_recv_frame failed with %d", ret);
    free(buf);
    return ret;
  }

  if (ws_pkt.type == HTTPD_WS_TYPE_PING || ws_pkt.type == HTTPD_WS_TYPE_CLOSE) {
    if (ws_pkt.type == HTTPD_WS_TYPE_PING) {
      ESP_LOGI(TAG, "Got a WS PING frame, Replying PONG");
      ws_pkt.type = HTTPD_WS_TYPE_PONG;
    } else if (ws_pkt.type == HTTPD_WS_TYPE_CLOSE) {
      ESP_LOGI(TAG, "Got a WS CLOSE frame, Replying CLOSE");
      ws_pkt.len = 0;
      ws_pkt.payload = NULL;
      xTaskNotifyGive(g_telemetry_task_handle);
      ulTaskNotifyTakeIndexed(TELEMETRY_STOPPED_NOTIFICATION_INDEX, pdTRUE, portMAX_DELAY);
    }

    ESP_LOGI(TAG, "Sending control frame from telemetry handler");
    ret = httpd_ws_send_frame(req, &ws_pkt);
    if (ret != ESP_OK) {
      ESP_LOGE(TAG, "httpd_ws_send_frame failed with %d", ret);
      free(buf);
      return ret;
    }
  }

  free(buf);
  return ret;
}

static esp_err_t telemetry_get_handler(httpd_req_t *req)
{
  if (g_server_task_handle == NULL) {
    g_server_task_handle = xTaskGetCurrentTaskHandle();
  }

  if (req->method == HTTP_GET) {
    ESP_ERROR_CHECK(telemetry_handle_handshake(req));
  } else {
    ESP_ERROR_CHECK(telemetry_handle_websocket_frame(req));
  }

  return ESP_OK;
}

void ws_telemetry_task(void* p) {
  ESP_LOGI(TAG, "Starting telemetry task");
  esp_err_t ret = ESP_OK;
  httpd_req_t* req = NULL;
  while (true) {
    if (req == NULL) {
      ESP_LOGI(TAG, "Waiting for notification to start the telemetry");
      if (xQueueReceive(g_telemetry_req_queue, &req, portMAX_DELAY) != pdPASS) {
        ESP_LOGE(TAG, "xQueueReceive(g_telemetry_req_queue) failed");
        break;
      }
      telemetry_start();
      ESP_LOGI(TAG, "telemetry started");
    }

    telemetry_packet_t packet = {};
    if (xQueueReceive(g_telemetry_packet_queue, &packet, portMAX_DELAY) != pdPASS) {
      ESP_LOGE(TAG, "xQueueReceive(g_telemetry_packet_queue) failed");
      break;
    }

    if (ulTaskNotifyTake(pdTRUE, 0) == 1) {
      if (httpd_req_async_handler_complete(req) != ESP_OK) {
        ESP_LOGE(TAG, "failed to complete async telemetry req");
      }
      req = NULL;
      telemetry_stop();
      ESP_LOGI(TAG, "telemetry stopped");
      xTaskNotifyGiveIndexed(g_server_task_handle, TELEMETRY_STOPPED_NOTIFICATION_INDEX);
      continue;
    }

    cJSON* packet_json = convert_telemetry_packet_to_json(packet);
    char* packet_json_str = cJSON_PrintUnformatted(packet_json);

    httpd_ws_frame_t ws_pkt = {};
    ws_pkt.type = HTTPD_WS_TYPE_TEXT;
    ws_pkt.payload = (uint8_t*)packet_json_str;
    ws_pkt.len = strlen(packet_json_str);

    ret = httpd_ws_send_frame(req, &ws_pkt);
    if (ret != ESP_OK) {
      ESP_LOGE(TAG, "httpd_ws_send_frame failed with %d", ret);
      cJSON_free(packet_json_str);
      cJSON_Delete(packet_json);
      break;
    }

    cJSON_free(packet_json_str);
    cJSON_Delete(packet_json);
  }
  ESP_LOGW(TAG, "telemetry task stopped");
  vTaskDelete(NULL);
}

static const httpd_uri_t telemetry = {
    .uri       = "/telemetry",
    .method    = HTTP_GET,
    .handler   = telemetry_get_handler,
    .user_ctx  = NULL,
    .is_websocket = true,
    .handle_ws_control_frames = true,
    .supported_subprotocol = NULL
};

static httpd_handle_t start_web_server()
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.lru_purge_enable = true;
    config.max_open_sockets = 3;

    ESP_LOGI(TAG, "Starting server on port: '%d'", config.server_port);
    if (httpd_start(&server, &config) == ESP_OK) {
        ESP_LOGI(TAG, "Registering URI handlers");
        httpd_register_uri_handler(server, &root);
        httpd_register_uri_handler(server, &stream);
        httpd_register_uri_handler(server, &telemetry);
        return server;
    }

    ESP_LOGI(TAG, "Error starting server!");
    return NULL;
}

static esp_err_t stop_web_server(httpd_handle_t server)
{
    g_server_task_handle = NULL;
    return httpd_stop(server);
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

void web_server_setup(QueueHandle_t frame_queue, QueueHandle_t command_queue, QueueHandle_t telemetry_queue) {
  g_frame_queue = frame_queue;
  g_command_queue = command_queue;
  g_telemetry_packet_queue = telemetry_queue;

  g_stream_req_queue = xQueueCreate(1, sizeof(httpd_req_t*));
  g_telemetry_req_queue = xQueueCreate(1, sizeof(httpd_req_t*));

  if (xTaskCreate(ws_stream_task, "ws_stream_task", 4096, (void *)0, 1, &g_stream_task_handle) != pdPASS) {
    ESP_LOGE(TAG, "xTaskCreate(ws_stream_task) failed");
    return;
  }
  if (xTaskCreate(ws_telemetry_task, "ws_telemetry_task", 4096, (void *)0, 1, &g_telemetry_task_handle) != pdPASS) {
    ESP_LOGE(TAG, "xTaskCreate(ws_telemetry_task) failed");
    return;
  }

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
