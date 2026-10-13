#include "web_server.hpp"
#include <atomic>
#include <cstdint>
#include "wifi.hpp"
#include "freertos/FreeRTOS.h"
#include "esp_heap_caps.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include <stdio.h>
#include <unistd.h>
#include "esp_err.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_log_otel.h"
#include "esp_camera.h"
#include "esp_http_server.h"
#include "esp_wifi.h"
#include "motor.hpp"
#include "camera.hpp"
#include "telemetry.hpp"
#include "tracing.hpp"
#include "esp_opentelemetry.hpp"
#include "opentelemetry/trace/scope.h"
#include "opentelemetry/trace/span_startoptions.h"
#include "web_server_metrics.hpp"
#include "socket_address.hpp"
#include <cJSON.h>
#include "mbedtls/base64.h"
#include "opentelemetry/trace/context.h"

static const char* TAG = "web_server";

static QueueHandle_t g_command_queue = NULL;

struct ws_connection_t {
  httpd_handle_t hd = nullptr;
  int fd = -1;
  void* token = nullptr;
  socket_address_t server = {};
  socket_address_t client = {};
};

// Never null: httpd reads a null context as absent.
static void* ws_next_token() {
  static std::atomic<uintptr_t> next{1};
  return reinterpret_cast<void*>(next.fetch_add(1));
}

// No-op to avoid freeing the token: httpd_sess_set_ctx() will call this on session close.
static void ws_keep_token(void* token) { (void)token; }

static bool ws_connection_is_live(const ws_connection_t& connection) {
  return connection.token != nullptr &&
         httpd_sess_get_ctx(connection.hd, connection.fd) == connection.token;
}

// One endpoint and the HTTP server instance that serves it. Each instance does all of its work on
// its own task, so a send that is blocked on one endpoint's client cannot delay another endpoint.
struct ws_endpoint_t {
  const char* path;
  uint16_t port;
  uint16_t ctrl_port;
  // 0 keeps the httpd default.
  size_t stack_size;
  esp_err_t (*handler)(httpd_req_t* req);
  httpd_handle_t server = nullptr;
  // Read and written only on this endpoint's httpd task.
  ws_connection_t owner = {};
  // The rest is used by the push endpoints only and stays NULL on the Drive endpoint.
  QueueHandle_t data_queue = NULL;
  QueueHandle_t req_queue = NULL;
  QueueHandle_t closed_queue = NULL;
  QueueSetHandle_t wait_set = NULL;
  QueueHandle_t sent_queue = NULL;
  std::atomic<void*> served{nullptr};
};

constexpr uint32_t WS_SEND_ABANDONED = 0;

static void ws_endpoint_init(ws_endpoint_t& endpoint, QueueHandle_t data_queue) {
  endpoint.data_queue = data_queue;
  endpoint.req_queue = xQueueCreate(1, sizeof(ws_connection_t));
  endpoint.closed_queue = xQueueCreate(1, sizeof(void*));
  endpoint.wait_set = xQueueCreateSet(uxQueueSpacesAvailable(data_queue) +
                                      uxQueueSpacesAvailable(endpoint.closed_queue));
  xQueueAddToSet(endpoint.data_queue, endpoint.wait_set);
  xQueueAddToSet(endpoint.closed_queue, endpoint.wait_set);
  endpoint.sent_queue = xQueueCreate(1, sizeof(uint32_t));
}

static esp_err_t ws_refuse_if_busy(httpd_req_t* req) {
  const auto* endpoint = static_cast<const ws_endpoint_t*>(req->user_ctx);
  if (!ws_connection_is_live(endpoint->owner)) {
    return ESP_OK;
  }
  ESP_LOGW(TAG, "Refusing %s: already serving a connection", req->uri);
  httpd_resp_set_status(req, "503 Service Unavailable");
  httpd_resp_send(req, NULL, 0);
  return ESP_FAIL;
}

static void ws_read_address(int (*read)(int, sockaddr*, socklen_t*), int fd,
                            socket_address_t* out) {
  sockaddr_storage address = {};
  socklen_t address_len = sizeof(address);
  if (read(fd, reinterpret_cast<sockaddr*>(&address), &address_len) != 0 ||
      !socket_address_format(address, out)) {
    ESP_LOGW(TAG, "Could not read an address of fd %d", fd);
  }
}

static esp_err_t ws_hand_over(httpd_req_t* req) {
  ESP_LOGI(TAG, "Handshake done, the new connection was opened");
  auto* endpoint = static_cast<ws_endpoint_t*>(req->user_ctx);
  ws_connection_t& owner = endpoint->owner;
  owner = {req->handle, httpd_req_to_sockfd(req), ws_next_token()};
  ws_read_address(getsockname, owner.fd, &owner.server);
  ws_read_address(getpeername, owner.fd, &owner.client);
  httpd_sess_set_ctx(owner.hd, owner.fd, owner.token, ws_keep_token);
  if (endpoint->req_queue != NULL) {
    xQueueOverwrite(endpoint->req_queue, &owner);
  }
  return ESP_OK;
}

static void ws_close_session(httpd_handle_t hd, int sockfd) {
  auto* endpoint = static_cast<ws_endpoint_t*>(httpd_get_global_user_ctx(hd));
  void* token = httpd_sess_get_ctx(hd, sockfd);
  if (token != nullptr && token == endpoint->owner.token) {
    endpoint->owner = {};
  }
  if (token != nullptr && token == endpoint->served.load()) {
    xQueueOverwrite(endpoint->closed_queue, &token);
    xQueueOverwrite(endpoint->sent_queue, &WS_SEND_ABANDONED);
  }
  close(sockfd);
}

static void ws_set_connection_attributes(opentelemetry::trace::Span& span,
                                         const ws_endpoint_t& endpoint,
                                         const ws_connection_t& connection) {
  span.SetAttribute("server.address", connection.server.host);
  span.SetAttribute("server.port", static_cast<int64_t>(connection.server.port));
  span.SetAttribute("client.address", connection.client.host);
  span.SetAttribute("client.port", static_cast<int64_t>(connection.client.port));
  span.SetAttribute("url.scheme", "ws");
  span.SetAttribute("url.path", endpoint.path);
  span.SetAttribute("network.transport", "tcp");
  span.SetAttribute("network.protocol.name", "websocket");
}

static bool ws_wait_for_item(const ws_endpoint_t& endpoint, const ws_connection_t& connection,
                             void* item) {
  while (true) {
    QueueSetMemberHandle_t ready = xQueueSelectFromSet(endpoint.wait_set, portMAX_DELAY);
    if (ready == endpoint.data_queue) {
      if (xQueueReceive(endpoint.data_queue, item, 0) == pdPASS) {
        return true;
      }
      continue;
    }
    void* closed = nullptr;
    if (xQueueReceive(endpoint.closed_queue, &closed, 0) == pdPASS && closed == connection.token) {
      return false;
    }
  }
}

struct ws_send_work_t {
  ws_connection_t connection;
  char* payload;
  size_t len;
  QueueHandle_t sent_queue;
  uint32_t seq;
};

constexpr int WS_SEND_DONE_TIMEOUT_MS = 10000;

static void ws_send_work(void* arg) {
  auto* work = static_cast<ws_send_work_t*>(arg);
  if (ws_connection_is_live(work->connection)) {
    httpd_ws_frame_t pkt = {};
    pkt.type = HTTPD_WS_TYPE_TEXT;
    pkt.payload = (uint8_t*)work->payload;
    pkt.len = work->len;
    if (httpd_ws_send_frame_async(work->connection.hd, work->connection.fd, &pkt) != ESP_OK) {
      ESP_LOGW(TAG, "httpd_ws_send_frame_async failed on fd %d", work->connection.fd);
    }
  }
  xQueueOverwrite(work->sent_queue, &work->seq);
  cJSON_free(work->payload);
  free(work);
}

static esp_err_t ws_queue_send(const ws_endpoint_t& endpoint, const ws_connection_t& connection,
                               char* payload, size_t len, uint32_t* seq) {
  static std::atomic<uint32_t> next_seq{WS_SEND_ABANDONED + 1};
  *seq = next_seq.fetch_add(1);
  if (*seq == WS_SEND_ABANDONED) {
    *seq = next_seq.fetch_add(1);
  }
  xQueueReset(endpoint.sent_queue);
  auto* work = static_cast<ws_send_work_t*>(malloc(sizeof(ws_send_work_t)));
  if (work == NULL) {
    cJSON_free(payload);
    return ESP_ERR_NO_MEM;
  }
  work->connection = connection;
  work->payload = payload;
  work->len = len;
  work->sent_queue = endpoint.sent_queue;
  work->seq = *seq;
  esp_err_t ret = httpd_queue_work(connection.hd, ws_send_work, work);
  if (ret != ESP_OK) {
    cJSON_free(payload);
    free(work);
  }
  return ret;
}

static void ws_wait_until_sent(const ws_endpoint_t& endpoint, uint32_t seq) {
  uint32_t sent = 0;
  while (xQueueReceive(endpoint.sent_queue, &sent, pdMS_TO_TICKS(WS_SEND_DONE_TIMEOUT_MS)) ==
         pdPASS) {
    if (sent == seq || sent == WS_SEND_ABANDONED) {
      return;
    }
  }
  ESP_LOGW(TAG, "Timed out waiting for a send to finish");
}

static esp_err_t drive_handler(httpd_req_t* req) {
  esp_err_t ret = ESP_OK;
  // Only the owner gets past the handshake, so the frame came from it.
  const auto* endpoint = static_cast<const ws_endpoint_t*>(req->user_ctx);
  const ws_connection_t connection = endpoint->owner;

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

  unsigned char* buf = NULL;
  if (ws_pkt.len > 0) {
    buf = (unsigned char*)malloc(ws_pkt.len + 1);
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

    cJSON* root = cJSON_Parse((const char*)ws_pkt.payload);
    auto parent_ctx = tracing_extract(root);
    cJSON_Delete(root);

    opentelemetry::trace::StartSpanOptions start_opts;
    start_opts.kind = opentelemetry::trace::SpanKind::kServer;
    start_opts.parent = opentelemetry::trace::GetSpan(parent_ctx)->GetContext();
    auto span = esp_opentelemetry_tracer()->StartSpan(
        "ws.command.receive",
        {{"ws.message.type", "command"},
         {"ws.message.size", static_cast<int64_t>(ws_pkt.len)},
         {"command.name", static_cast<int64_t>(packet.command)},
         {"command.value", static_cast<int64_t>(packet.value)}},
        start_opts);
    ws_set_connection_attributes(*span, *endpoint, connection);
    auto scope = opentelemetry::trace::Scope(span);

    // The command queue is a depth-1 mailbox: the latest command wins and this
    // handler never blocks on a full queue.
    if (xQueueOverwrite(g_command_queue, &packet) != pdPASS) {
      ESP_LOGE(TAG, "xQueueOverwrite failed");
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
    ws_set_connection_attributes(*span, *endpoint, connection);
    span->End();
  }

  free(buf);
  return ret;
}

// A push endpoint's client only reads, so there is nothing to handle after the handshake.
static esp_err_t push_handler(httpd_req_t* req) {
  (void)req;
  return ESP_OK;
}

static ws_endpoint_t g_drive{.path = "/",
                             .port = WEB_SERVER_DRIVE_PORT,
                             .ctrl_port = ESP_HTTPD_DEF_CTRL_PORT,
                             // 8 KB is insufficient for drive_handler with tracing_extract +
                             // StartSpan.
                             .stack_size = 16384,
                             .handler = drive_handler};
static ws_endpoint_t g_camera{.path = "/stream",
                              .port = WEB_SERVER_CAMERA_PORT,
                              .ctrl_port = ESP_HTTPD_DEF_CTRL_PORT + 1,
                              .stack_size = 0,
                              .handler = push_handler};
static ws_endpoint_t g_telemetry{.path = "/telemetry",
                                 .port = WEB_SERVER_TELEMETRY_PORT,
                                 .ctrl_port = ESP_HTTPD_DEF_CTRL_PORT + 2,
                                 .stack_size = 0,
                                 .handler = push_handler};
static ws_endpoint_t* const g_endpoints[] = {&g_drive, &g_camera, &g_telemetry};

void ws_stream_task(void* p) {
  ESP_LOGI(TAG, "Starting stream task");
  camera_fb_t* frame = NULL;
  ws_connection_t connection = {NULL, -1};
  bool active = false;
  opentelemetry::nostd::shared_ptr<opentelemetry::trace::Span> connection_span;

  auto teardown = [&]() {
    active = false;
    g_camera.served = nullptr;
    camera_stop();
    ESP_LOGI(TAG, "Stream stopped");
    connection_span->End();
    connection_span = nullptr;
  };

  while (true) {
    if (!active) {
      ESP_LOGI(TAG, "Waiting for notification to start the stream");
      if (xQueueReceive(g_camera.req_queue, &connection, portMAX_DELAY) != pdPASS) {
        ESP_LOGE(TAG, "xQueueReceive(g_camera.req_queue) failed");
        break;
      }
      g_camera.served = connection.token;
      if (!ws_connection_is_live(connection)) {
        ESP_LOGI(TAG, "Queued stream connection was closed before it started");
        g_camera.served = nullptr;
        continue;
      }
      opentelemetry::trace::StartSpanOptions stream_opts;
      stream_opts.kind = opentelemetry::trace::SpanKind::kServer;
      connection_span = esp_opentelemetry_tracer()->StartSpan("ws.stream.connection", stream_opts);
      ws_set_connection_attributes(*connection_span, g_camera, connection);
      camera_start();
      active = true;
      ESP_LOGI(TAG, "Stream started");
    }

    if (!ws_wait_for_item(g_camera, connection, &frame)) {
      teardown();
      continue;
    }
    if (!ws_connection_is_live(connection)) {
      esp_camera_fb_return(frame);
      teardown();
      continue;
    }

    opentelemetry::trace::StartSpanOptions send_opts;
    send_opts.kind = opentelemetry::trace::SpanKind::kProducer;
    send_opts.parent = connection_span->GetContext();
    auto send_span = esp_opentelemetry_tracer()->StartSpan(
        "ws.stream.send",
        {{"ws.message.type", "stream"}, {"ws.frame.size", static_cast<int64_t>(frame->len)}},
        send_opts);
    ws_set_connection_attributes(*send_span, g_camera, connection);
    auto send_scope = opentelemetry::trace::Scope(send_span);

    size_t b64_len = 0;
    mbedtls_base64_encode(NULL, 0, &b64_len, frame->buf, frame->len);
    char* b64_buf = (char*)heap_caps_malloc(b64_len + 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!b64_buf) {
      ESP_LOGE(TAG, "Failed to allocate base64 buffer");
      send_span->SetStatus(opentelemetry::trace::StatusCode::kError, "alloc failed");
      send_span->End();
      esp_camera_fb_return(frame);
      continue;
    }
    mbedtls_base64_encode((unsigned char*)b64_buf, b64_len + 1, &b64_len, frame->buf, frame->len);
    b64_buf[b64_len] = '\0';

    cJSON* packet_json = cJSON_CreateObject();
    cJSON_AddStringToObject(packet_json, "data", b64_buf);
    heap_caps_free(b64_buf);
    tracing_inject(packet_json);

    char* packet_json_str = cJSON_PrintUnformatted(packet_json);
    cJSON_Delete(packet_json);
    size_t payload_len = strlen(packet_json_str);
    send_span->SetAttribute("ws.message.size", static_cast<int64_t>(payload_len));

    uint32_t seq = 0;
    esp_err_t ret = ws_queue_send(g_camera, connection, packet_json_str, payload_len, &seq);
    if (ret != ESP_OK) {
      ESP_LOGW(TAG, "ws_queue_send failed: %s", esp_err_to_name(ret));
      send_span->SetStatus(opentelemetry::trace::StatusCode::kError, "ws send failed");
      send_span->End();
      esp_camera_fb_return(frame);
      continue;
    }

    web_server_metrics_update();
    esp_camera_fb_return(frame);
    ws_wait_until_sent(g_camera, seq);
    send_span->End();
  }
  ESP_LOGW(TAG, "Stream task stopped");
  vTaskDelete(NULL);
}

void ws_telemetry_task(void* p) {
  ESP_LOGI(TAG, "Starting telemetry WS task");
  ws_connection_t connection = {NULL, -1};
  bool active = false;
  opentelemetry::nostd::shared_ptr<opentelemetry::trace::Span> connection_span;

  auto teardown = [&]() {
    active = false;
    g_telemetry.served = nullptr;
    telemetry_stop();
    ESP_LOGI(TAG, "Telemetry stopped");
    connection_span->End();
    connection_span = nullptr;
  };

  while (true) {
    if (!active) {
      ESP_LOGI(TAG, "Waiting for notification to start the telemetry");
      if (xQueueReceive(g_telemetry.req_queue, &connection, portMAX_DELAY) != pdPASS) {
        ESP_LOGE(TAG, "xQueueReceive(g_telemetry.req_queue) failed");
        break;
      }
      g_telemetry.served = connection.token;
      if (!ws_connection_is_live(connection)) {
        ESP_LOGI(TAG, "Queued telemetry connection was closed before it started");
        g_telemetry.served = nullptr;
        continue;
      }
      opentelemetry::trace::StartSpanOptions telemetry_opts;
      telemetry_opts.kind = opentelemetry::trace::SpanKind::kServer;
      connection_span =
          esp_opentelemetry_tracer()->StartSpan("ws.telemetry.connection", telemetry_opts);
      ws_set_connection_attributes(*connection_span, g_telemetry, connection);
      telemetry_start();
      active = true;
      ESP_LOGI(TAG, "Telemetry started");
    }

    telemetry_packet_t packet = {};
    if (!ws_wait_for_item(g_telemetry, connection, &packet)) {
      teardown();
      continue;
    }
    if (!ws_connection_is_live(connection)) {
      teardown();
      continue;
    }

    cJSON* packet_json = convert_telemetry_packet_to_json(packet);

    opentelemetry::trace::StartSpanOptions send_opts;
    send_opts.kind = opentelemetry::trace::SpanKind::kProducer;
    send_opts.parent = connection_span->GetContext();
    auto send_span = esp_opentelemetry_tracer()->StartSpan(
        "ws.telemetry.send", {{"ws.message.type", "telemetry"}}, send_opts);
    ws_set_connection_attributes(*send_span, g_telemetry, connection);
    auto send_scope = opentelemetry::trace::Scope(send_span);
    tracing_inject(packet_json);

    char* packet_json_str = cJSON_PrintUnformatted(packet_json);
    cJSON_Delete(packet_json);
    size_t payload_len = strlen(packet_json_str);
    send_span->SetAttribute("ws.message.size", static_cast<int64_t>(payload_len));

    uint32_t seq = 0;
    esp_err_t ret = ws_queue_send(g_telemetry, connection, packet_json_str, payload_len, &seq);
    if (ret != ESP_OK) {
      ESP_LOGW(TAG, "ws_queue_send failed: %s", esp_err_to_name(ret));
      send_span->SetStatus(opentelemetry::trace::StatusCode::kError, "ws send failed");
      send_span->End();
      continue;
    }

    ws_wait_until_sent(g_telemetry, seq);
    send_span->End();
  }
  ESP_LOGW(TAG, "Telemetry task stopped");
  vTaskDelete(NULL);
}

// No-op: global_user_ctx points at a static endpoint, which httpd_stop() must not free.
static void ws_keep_endpoint(void* endpoint) { (void)endpoint; }

static esp_err_t start_endpoint_server(ws_endpoint_t& endpoint) {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = endpoint.port;
  config.ctrl_port = endpoint.ctrl_port;
  // The owner and one connection being refused. With LRU purge on, that connection would evict the
  // owner before the refusal runs.
  config.max_open_sockets = 2;
  config.lru_purge_enable = false;
  if (endpoint.stack_size != 0) {
    config.stack_size = endpoint.stack_size;
  }
  config.global_user_ctx = &endpoint;
  config.global_user_ctx_free_fn = ws_keep_endpoint;
  config.close_fn = ws_close_session;

  ESP_LOGI(TAG, "Starting the %s server on port %d", endpoint.path, endpoint.port);
  esp_err_t err = httpd_start(&endpoint.server, &config);
  if (err != ESP_OK) {
    endpoint.server = nullptr;
    return err;
  }
  const httpd_uri_t uri = {
      .uri = endpoint.path,
      .method = HTTP_GET,
      .handler = endpoint.handler,
      .user_ctx = &endpoint,
      .is_websocket = true,
      .handle_ws_control_frames = false,
      .supported_subprotocol = NULL,
      .ws_pre_handshake_cb = ws_refuse_if_busy,
      .ws_post_handshake_cb = ws_hand_over,
  };
  return httpd_register_uri_handler(endpoint.server, &uri);
}

static void stop_web_servers() {
  for (ws_endpoint_t* endpoint : g_endpoints) {
    if (endpoint->server == nullptr) {
      continue;
    }
    ESP_LOGI(TAG, "Stopping the %s server", endpoint->path);
    if (httpd_stop(endpoint->server) != ESP_OK) {
      ESP_LOGE(TAG, "Failed to stop the %s server", endpoint->path);
      continue;
    }
    endpoint->server = nullptr;
  }
}

// Starts every server that is not running. The servers run all together or not at all, so a
// server that fails to start stops the others.
static void start_web_servers() {
  bool started = false;
  for (ws_endpoint_t* endpoint : g_endpoints) {
    if (endpoint->server != nullptr) {
      continue;
    }
    esp_err_t err = start_endpoint_server(*endpoint);
    if (err != ESP_OK) {
      ESP_LOGE(TAG, "Error starting the %s server: %s", endpoint->path, esp_err_to_name(err));
      stop_web_servers();
      return;
    }
    started = true;
  }
  if (started) {
    ESP_LOGI(TAG, "Serving every endpoint");
  }
}

static void web_server_handler_on_got_ip(void* arg, esp_event_base_t event_base, int32_t event_id,
                                         void* event_data) {
  start_web_servers();
}

static void web_server_handler_on_wifi_disconnect(void* arg, esp_event_base_t event_base,
                                                  int32_t event_id, void* event_data) {
  stop_web_servers();
}

void web_server_setup(QueueHandle_t frame_queue, QueueHandle_t command_queue,
                      QueueHandle_t telemetry_queue) {
  g_command_queue = command_queue;
  ws_endpoint_init(g_camera, frame_queue);
  ws_endpoint_init(g_telemetry, telemetry_queue);

  {
    // Allocate ws_stream_task stack from PSRAM: base64 encoding of VGA JPEG frames plus
    // cJSON serialization and OTel span creation exhaust an 8KB DRAM stack.
    StackType_t* stream_stack =
        static_cast<StackType_t*>(heap_caps_malloc(32768, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    StaticTask_t* stream_tcb = static_cast<StaticTask_t*>(
        heap_caps_malloc(sizeof(StaticTask_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    if (!stream_stack || !stream_tcb) {
      ESP_LOGE(TAG, "xTaskCreate(ws_stream_task) failed - no PSRAM");
      return;
    }
    xTaskCreateStaticPinnedToCore(ws_stream_task, "ws_stream_task", 32768 / sizeof(StackType_t),
                                  nullptr, 1, stream_stack, stream_tcb, tskNO_AFFINITY);
  }
  {
    // Allocate ws_telemetry_task stack from PSRAM to avoid exhausting internal DRAM.
    StackType_t* tel_stack =
        static_cast<StackType_t*>(heap_caps_malloc(32768, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    StaticTask_t* tel_tcb = static_cast<StaticTask_t*>(
        heap_caps_malloc(sizeof(StaticTask_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    if (!tel_stack || !tel_tcb) {
      ESP_LOGE(TAG, "xTaskCreate(ws_telemetry_task) failed - no PSRAM");
      return;
    }
    xTaskCreateStaticPinnedToCore(ws_telemetry_task, "ws_telemetry_task",
                                  32768 / sizeof(StackType_t), nullptr, 1, tel_stack, tel_tcb,
                                  tskNO_AFFINITY);
  }

  // Start the servers before registering event handlers to avoid a race where
  // IP_EVENT_STA_GOT_IP fires in the gap and on_got_ip starts them on another task
  // while this function is still about to call start_web_servers().
  start_web_servers();

  ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                             &web_server_handler_on_got_ip, nullptr));
  ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED,
                                             &web_server_handler_on_wifi_disconnect, nullptr));
}
