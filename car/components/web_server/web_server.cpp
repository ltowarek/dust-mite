#include "web_server.hpp"
#include "wifi.hpp"
#include "freertos/FreeRTOS.h"
#include "esp_heap_caps.h"
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
#include "motor.hpp"
#include "camera.hpp"
#include "telemetry.hpp"
#include "tracing.hpp"
#include <cJSON.h>
#include "mbedtls/base64.h"
#include "opentelemetry/trace/context.h"

static const char* TAG = "web_server";

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

// Connection-level spans live across task/queue boundaries, so stash them
// in file-scope shared_ptrs guarded by the single-producer/single-consumer
// lifecycle of the stream/telemetry handlers.
static opentelemetry::nostd::shared_ptr<opentelemetry::trace::Span> g_stream_connection_span;
static opentelemetry::nostd::shared_ptr<opentelemetry::trace::Span> g_telemetry_connection_span;

static esp_err_t root_get_handler(httpd_req_t *req) {
  esp_err_t ret = ESP_OK;

  if (req->method == HTTP_GET) {
    ESP_LOGI(TAG, "Handshake done, the new connection was opened");
    return ESP_OK;
  }

  httpd_ws_frame_t ws_pkt = {};
  ret = httpd_ws_recv_frame(req, &ws_pkt, 0);
  if (ret != ESP_OK) {
    ESP_LOGW(TAG, "Failed to receive WS frame header: %s", esp_err_to_name(ret));
    return ret;
  }
  ESP_LOGI(TAG, "Frame len is %d", ws_pkt.len);

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

  command_packet_t packet = {};
  if (parse_command_packet((const char*)ws_pkt.payload, &packet)) {
      ESP_LOGI(TAG, "JSON={\"command\": %d, \"value\": %d}", packet.command, packet.value);

      cJSON *root = cJSON_Parse((const char*)ws_pkt.payload);
      auto parent_ctx = tracing_extract(*root);
      cJSON_Delete(root);

      opentelemetry::trace::StartSpanOptions start_opts;
      start_opts.kind   = opentelemetry::trace::SpanKind::kServer;
      start_opts.parent = opentelemetry::trace::GetSpan(parent_ctx)->GetContext();
      auto span = esp_opentelemetry_tracer()->StartSpan(
          "ws.command.receive",
          {{"ws.url", "/"},
           {"network.protocol.name", "websocket"},
           {"ws.message.type", "command"},
           {"ws.message.size", static_cast<int64_t>(ws_pkt.len)},
           {"command.name", static_cast<int64_t>(packet.command)},
           {"command.value", static_cast<int64_t>(packet.value)}},
          start_opts);
      auto scope = opentelemetry::trace::Scope(span);

      if (xQueueSendToBack(g_command_queue, &packet, portMAX_DELAY) != pdPASS) {
        ESP_LOGE(TAG, "xQueueSendToBack failed");
        span->SetStatus(opentelemetry::trace::StatusCode::kError, "queue send failed");
        span->End();
        free(buf);
        return ESP_FAIL;
      }
      span->End();
  } else {
    ESP_LOGW(TAG, "Failed to parse JSON: %s", ws_pkt.payload);
    auto span = esp_opentelemetry_tracer()->StartSpan("ws.command.receive");
    span->SetStatus(opentelemetry::trace::StatusCode::kError, "json parse failed");
    span->SetAttribute("ws.message.size", static_cast<int64_t>(ws_pkt.len));
    span->End();
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
    .supported_subprotocol = NULL,
    .ws_post_handshake_cb = NULL,
};

static esp_err_t stream_handle_handshake(httpd_req_t *req) {
  if (g_server_task_handle == NULL) {
    g_server_task_handle = xTaskGetCurrentTaskHandle();
  }
  ESP_LOGI(TAG, "Handshake done, the new connection was opened");
  opentelemetry::trace::StartSpanOptions stream_opts;
  stream_opts.kind = opentelemetry::trace::SpanKind::kServer;
  g_stream_connection_span = esp_opentelemetry_tracer()->StartSpan(
      "ws.stream.connection",
      {{"ws.url", "/stream"},
       {"network.protocol.name", "websocket"}},
      stream_opts);
  httpd_req_t* copy = NULL;
  esp_err_t ret = httpd_req_async_handler_begin(req, &copy);
  if (ret != ESP_OK) {
    ESP_LOGE(TAG, "httpd_req_async_handler_begin failed: %s", esp_err_to_name(ret));
    g_stream_connection_span->SetStatus(opentelemetry::trace::StatusCode::kError,
                                        "async begin failed");
    g_stream_connection_span->End();
    return ret;
  }
  if (xQueueSendToBack(g_stream_req_queue, &copy, portMAX_DELAY) != pdPASS) {
    ESP_LOGE(TAG, "xQueueSendToBack(g_stream_req_queue) failed");
    g_stream_connection_span->SetStatus(opentelemetry::trace::StatusCode::kError,
                                        "queue send failed");
    g_stream_connection_span->End();
    return ESP_FAIL;
  }
  return ESP_OK;
}

static esp_err_t stream_handle_websocket_frame(httpd_req_t *req) {
  esp_err_t ret = ESP_OK;

  httpd_ws_frame_t ws_pkt = {};
  ret = httpd_ws_recv_frame(req, &ws_pkt, 0);
  if (ret != ESP_OK) {
    ESP_LOGW(TAG, "Failed to receive stream WS frame header: %s", esp_err_to_name(ret));
    xTaskNotifyGive(g_stream_task_handle);
    return ret;
  }

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
      if (g_stream_connection_span) {
        g_stream_connection_span->SetAttribute(
            "ws.close.code", static_cast<int64_t>(ws_pkt.len));
      }
      ws_pkt.len = 0;
      ws_pkt.payload = NULL;
      xTaskNotifyGive(g_stream_task_handle);
      ulTaskNotifyTakeIndexed(CAMERA_STOPPED_NOTIFICATION_INDEX, pdTRUE, pdMS_TO_TICKS(2000));
    }

    ESP_LOGI(TAG, "Sending control frame from stream handler");
    ret = httpd_ws_send_frame(req, &ws_pkt);
    if (ret != ESP_OK) {
      // CLOSE reply failure is not an error: the peer may have already closed
      // the TCP connection (ENOTCONN/ECONNRESET) which is what triggered CLOSE
      // in the first place. Log at warn level and treat the handler as done.
      ESP_LOGW(TAG, "httpd_ws_send_frame failed with %d", ret);
      free(buf);
      return ESP_OK;
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
  return stream_handle_websocket_frame(req);
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

    bool stream_stopped = false;
    while (xQueueReceive(g_frame_queue, &frame, pdMS_TO_TICKS(100)) != pdPASS) {
      if (ulTaskNotifyTake(pdTRUE, 0) == 1) {
        stream_stopped = true;
        break;
      }
    }
    if (stream_stopped) {
      // Signal the CLOSE handler before releasing the async handle so it can
      // still send the CLOSE reply while the socket is in a valid async state.
      xTaskNotifyGiveIndexed(g_server_task_handle, CAMERA_STOPPED_NOTIFICATION_INDEX);
      if (httpd_req_async_handler_complete(req) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to complete async stream req");
      }
      req = NULL;
      camera_stop();
      ESP_LOGI(TAG, "Stream stopped");
      if (g_stream_connection_span) {
        g_stream_connection_span->End();
        g_stream_connection_span = opentelemetry::nostd::shared_ptr<opentelemetry::trace::Span>{};
      }
      continue;
    }

    if (ulTaskNotifyTake(pdTRUE, 0) == 1) {
      esp_camera_fb_return(frame);
      // Signal the CLOSE handler before releasing the async handle so it can
      // still send the CLOSE reply while the socket is in a valid async state.
      xTaskNotifyGiveIndexed(g_server_task_handle, CAMERA_STOPPED_NOTIFICATION_INDEX);
      if (httpd_req_async_handler_complete(req) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to complete async stream req");
      }
      req = NULL;
      camera_stop();
      ESP_LOGI(TAG, "Stream stopped");
      if (g_stream_connection_span) {
        g_stream_connection_span->End();
        g_stream_connection_span = opentelemetry::nostd::shared_ptr<opentelemetry::trace::Span>{};
      }
      continue;
    }

    opentelemetry::trace::StartSpanOptions send_opts;
    send_opts.kind = opentelemetry::trace::SpanKind::kProducer;
    send_opts.parent = g_stream_connection_span->GetContext();
    auto send_span = esp_opentelemetry_tracer()->StartSpan(
        "ws.stream.send",
        {{"ws.url", "/stream"},
         {"network.protocol.name", "websocket"},
         {"ws.message.type", "stream"},
         {"ws.frame.size", static_cast<int64_t>(frame->len)}},
        send_opts);
    auto send_scope = opentelemetry::trace::Scope(send_span);

    size_t b64_len = 0;
    mbedtls_base64_encode(NULL, 0, &b64_len, frame->buf, frame->len);
    char* b64_buf = (char*)heap_caps_malloc(b64_len + 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!b64_buf) {
      ESP_LOGE(TAG, "Failed to allocate base64 buffer");
      send_span->SetStatus(opentelemetry::trace::StatusCode::kError, "alloc failed");
      send_span->End();
      esp_camera_fb_return(frame);
      if (httpd_req_async_handler_complete(req) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to complete async stream req");
      }
      req = NULL;
      camera_stop();
      if (g_stream_connection_span) {
        g_stream_connection_span->End();
        g_stream_connection_span = opentelemetry::nostd::shared_ptr<opentelemetry::trace::Span>{};
      }
      // No notification: same rationale as the send-error path below.
      continue;
    }
    mbedtls_base64_encode((unsigned char*)b64_buf, b64_len + 1, &b64_len, frame->buf, frame->len);
    b64_buf[b64_len] = '\0';

    cJSON* packet_json = cJSON_CreateObject();
    cJSON_AddStringToObject(packet_json, "data", b64_buf);
    heap_caps_free(b64_buf);
    tracing_inject(*packet_json);

    char* packet_json_str = cJSON_PrintUnformatted(packet_json);
    cJSON_Delete(packet_json);

    httpd_ws_frame_t ws_pkt = {};
    ws_pkt.type = HTTPD_WS_TYPE_TEXT;
    ws_pkt.payload = (uint8_t*)packet_json_str;
    ws_pkt.len = strlen(packet_json_str);
    send_span->SetAttribute("ws.message.size", static_cast<int64_t>(ws_pkt.len));

    ret = httpd_ws_send_frame(req, &ws_pkt);
    if (ret != ESP_OK) {
      ESP_LOGE(TAG, "httpd_ws_send_frame failed: %s", esp_err_to_name(ret));
      send_span->SetStatus(opentelemetry::trace::StatusCode::kError, "ws send failed");
      send_span->End();
      cJSON_free(packet_json_str);
      esp_camera_fb_return(frame);
      if (httpd_req_async_handler_complete(req) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to complete async stream req");
      }
      req = NULL;
      camera_stop();
      if (g_stream_connection_span) {
        g_stream_connection_span->End();
        g_stream_connection_span = opentelemetry::nostd::shared_ptr<opentelemetry::trace::Span>{};
      }
      // Do NOT notify g_server_task_handle here: no CLOSE handler is waiting,
      // and a spurious notification would be consumed as a stale one by the next
      // CLOSE handler, causing it to skip its wait and send on a dead socket.
      continue;
    }

    send_span->End();
    cJSON_free(packet_json_str);
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
    .supported_subprotocol = NULL,
    .ws_post_handshake_cb = stream_handle_handshake,
};

static esp_err_t telemetry_handle_handshake(httpd_req_t *req) {
  if (g_server_task_handle == NULL) {
    g_server_task_handle = xTaskGetCurrentTaskHandle();
  }
  ESP_LOGI(TAG, "Handshake done, the new connection was opened");
  opentelemetry::trace::StartSpanOptions tel_opts;
  tel_opts.kind = opentelemetry::trace::SpanKind::kServer;
  g_telemetry_connection_span = esp_opentelemetry_tracer()->StartSpan(
      "ws.telemetry.connection",
      {{"ws.url", "/telemetry"},
       {"network.protocol.name", "websocket"}},
      tel_opts);
  httpd_req_t* copy = NULL;
  esp_err_t ret = httpd_req_async_handler_begin(req, &copy);
  if (ret != ESP_OK) {
    ESP_LOGE(TAG, "httpd_req_async_handler_begin failed: %s", esp_err_to_name(ret));
    g_telemetry_connection_span->SetStatus(opentelemetry::trace::StatusCode::kError,
                                           "async begin failed");
    g_telemetry_connection_span->End();
    return ret;
  }
  if (xQueueSendToBack(g_telemetry_req_queue, &copy, portMAX_DELAY) != pdPASS) {
    ESP_LOGE(TAG, "xQueueSendToBack(g_telemetry_req_queue) failed");
    g_telemetry_connection_span->SetStatus(opentelemetry::trace::StatusCode::kError,
                                           "queue send failed");
    g_telemetry_connection_span->End();
    return ESP_FAIL;
  }
  return ESP_OK;
}

static esp_err_t telemetry_handle_websocket_frame(httpd_req_t *req) {
  esp_err_t ret = ESP_OK;

  httpd_ws_frame_t ws_pkt = {};
  ret = httpd_ws_recv_frame(req, &ws_pkt, 0);
  if (ret != ESP_OK) {
    ESP_LOGW(TAG, "Failed to receive telemetry WS frame header: %s", esp_err_to_name(ret));
    xTaskNotifyGive(g_telemetry_task_handle);
    return ret;
  }

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
      if (g_telemetry_connection_span) {
        g_telemetry_connection_span->SetAttribute(
            "ws.close.code", static_cast<int64_t>(ws_pkt.len));
      }
      ws_pkt.len = 0;
      ws_pkt.payload = NULL;
      xTaskNotifyGive(g_telemetry_task_handle);
      ulTaskNotifyTakeIndexed(TELEMETRY_STOPPED_NOTIFICATION_INDEX, pdTRUE, pdMS_TO_TICKS(2000));
    }

    ESP_LOGI(TAG, "Sending control frame from telemetry handler");
    ret = httpd_ws_send_frame(req, &ws_pkt);
    if (ret != ESP_OK) {
      // CLOSE reply failure is not an error: the peer may have already closed
      // the TCP connection (ENOTCONN/ECONNRESET) which is what triggered CLOSE
      // in the first place. Log at warn level and treat the handler as done.
      ESP_LOGW(TAG, "httpd_ws_send_frame failed with %d", ret);
      free(buf);
      return ESP_OK;
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
  return telemetry_handle_websocket_frame(req);
}

void ws_telemetry_task(void* p) {
  ESP_LOGI(TAG, "Starting telemetry WS task");
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
      ESP_LOGI(TAG, "Telemetry started");
    }

    telemetry_packet_t packet = {};
    bool telemetry_stopped = false;
    while (xQueueReceive(g_telemetry_packet_queue, &packet, pdMS_TO_TICKS(100)) != pdPASS) {
      if (ulTaskNotifyTake(pdTRUE, 0) == 1) {
        telemetry_stopped = true;
        break;
      }
    }
    if (telemetry_stopped) {
      // Signal the CLOSE handler before releasing the async handle so it can
      // still send the CLOSE reply while the socket is in a valid async state.
      xTaskNotifyGiveIndexed(g_server_task_handle, TELEMETRY_STOPPED_NOTIFICATION_INDEX);
      if (httpd_req_async_handler_complete(req) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to complete async telemetry req");
      }
      req = NULL;
      telemetry_stop();
      ESP_LOGI(TAG, "Telemetry stopped");
      if (g_telemetry_connection_span) {
        g_telemetry_connection_span->End();
        g_telemetry_connection_span = opentelemetry::nostd::shared_ptr<opentelemetry::trace::Span>{};
      }
      continue;
    }

    if (ulTaskNotifyTake(pdTRUE, 0) == 1) {
      // Signal the CLOSE handler before releasing the async handle so it can
      // still send the CLOSE reply while the socket is in a valid async state.
      xTaskNotifyGiveIndexed(g_server_task_handle, TELEMETRY_STOPPED_NOTIFICATION_INDEX);
      if (httpd_req_async_handler_complete(req) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to complete async telemetry req");
      }
      req = NULL;
      telemetry_stop();
      ESP_LOGI(TAG, "Telemetry stopped");
      if (g_telemetry_connection_span) {
        g_telemetry_connection_span->End();
        g_telemetry_connection_span = opentelemetry::nostd::shared_ptr<opentelemetry::trace::Span>{};
      }
      continue;
    }

    cJSON* packet_json = convert_telemetry_packet_to_json(packet);

    opentelemetry::trace::StartSpanOptions send_opts;
    send_opts.kind = opentelemetry::trace::SpanKind::kProducer;
    send_opts.parent = g_telemetry_connection_span->GetContext();
    auto send_span = esp_opentelemetry_tracer()->StartSpan(
        "ws.telemetry.send",
        {{"ws.url", "/telemetry"},
         {"network.protocol.name", "websocket"},
         {"ws.message.type", "telemetry"}},
        send_opts);
    auto send_scope = opentelemetry::trace::Scope(send_span);
    tracing_inject(*packet_json);

    char* packet_json_str = cJSON_PrintUnformatted(packet_json);

    httpd_ws_frame_t ws_pkt = {};
    ws_pkt.type = HTTPD_WS_TYPE_TEXT;
    ws_pkt.payload = (uint8_t*)packet_json_str;
    ws_pkt.len = strlen(packet_json_str);
    send_span->SetAttribute("ws.message.size", static_cast<int64_t>(ws_pkt.len));

    ret = httpd_ws_send_frame(req, &ws_pkt);
    if (ret != ESP_OK) {
      ESP_LOGE(TAG, "httpd_ws_send_frame failed with %d", ret);
      send_span->SetStatus(opentelemetry::trace::StatusCode::kError, "ws send failed");
      send_span->End();
      cJSON_free(packet_json_str);
      cJSON_Delete(packet_json);
      if (httpd_req_async_handler_complete(req) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to complete async telemetry req");
      }
      req = NULL;
      telemetry_stop();
      if (g_telemetry_connection_span) {
        g_telemetry_connection_span->End();
        g_telemetry_connection_span = opentelemetry::nostd::shared_ptr<opentelemetry::trace::Span>{};
      }
      // Do NOT notify g_server_task_handle here: no CLOSE handler is waiting,
      // and a spurious notification would be consumed as a stale one by the next
      // CLOSE handler, causing it to skip its wait and send on a dead socket.
      continue;
    }

    send_span->End();
    cJSON_free(packet_json_str);
    cJSON_Delete(packet_json);
  }
  ESP_LOGW(TAG, "Telemetry task stopped");
  vTaskDelete(NULL);
}

static const httpd_uri_t telemetry = {
    .uri       = "/telemetry",
    .method    = HTTP_GET,
    .handler   = telemetry_get_handler,
    .user_ctx  = NULL,
    .is_websocket = true,
    .handle_ws_control_frames = true,
    .supported_subprotocol = NULL,
    .ws_post_handshake_cb = telemetry_handle_handshake,
};

static httpd_handle_t start_web_server()
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.lru_purge_enable = true;
    config.max_open_sockets = 3;
    // 8 KB is insufficient for root_get_handler with tracing_extract + StartSpan.
    config.stack_size = 16384;

    ESP_LOGI(TAG, "Starting server on port: '%d'", config.server_port);
    esp_err_t err = httpd_start(&server, &config);
    if (err == ESP_OK) {
        ESP_LOGI(TAG, "Registering URI handlers");
        httpd_register_uri_handler(server, &root);
        httpd_register_uri_handler(server, &stream);
        httpd_register_uri_handler(server, &telemetry);
        return server;
    }

    ESP_LOGE(TAG, "Error starting server: %s", esp_err_to_name(err));
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

  {
    // Allocate ws_stream_task stack from PSRAM: base64 encoding of VGA JPEG frames plus
    // cJSON serialization and OTel span creation exhaust an 8KB DRAM stack.
    StackType_t *stream_stack = static_cast<StackType_t*>(
        heap_caps_malloc(32768, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    StaticTask_t *stream_tcb = static_cast<StaticTask_t*>(
        heap_caps_malloc(sizeof(StaticTask_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    if (!stream_stack || !stream_tcb) {
      ESP_LOGE(TAG, "xTaskCreate(ws_stream_task) failed - no PSRAM");
      return;
    }
    g_stream_task_handle = xTaskCreateStaticPinnedToCore(
        ws_stream_task, "ws_stream_task",
        32768 / sizeof(StackType_t), nullptr, 1,
        stream_stack, stream_tcb, tskNO_AFFINITY);
  }
  {
    // Allocate ws_telemetry_task stack from PSRAM to avoid exhausting internal DRAM.
    StackType_t *tel_stack = static_cast<StackType_t*>(
        heap_caps_malloc(32768, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    StaticTask_t *tel_tcb = static_cast<StaticTask_t*>(
        heap_caps_malloc(sizeof(StaticTask_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    if (!tel_stack || !tel_tcb) {
      ESP_LOGE(TAG, "xTaskCreate(ws_telemetry_task) failed - no PSRAM");
      return;
    }
    g_telemetry_task_handle = xTaskCreateStaticPinnedToCore(
        ws_telemetry_task, "ws_telemetry_task",
        32768 / sizeof(StackType_t), nullptr, 1,
        tel_stack, tel_tcb, tskNO_AFFINITY);
  }

  // Start the server before registering event handlers to avoid a race where
  // IP_EVENT_STA_GOT_IP fires in the gap and on_got_ip starts a second server
  // instance while this function is still about to call start_web_server().
  server = start_web_server();

  ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &web_server_handler_on_got_ip, &server));
  ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED, &web_server_handler_on_wifi_disconnect, &server));
}

