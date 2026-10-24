#include "web_server.hpp"
#include <atomic>
#include <cstdint>
#include "wifi.hpp"
#include "freertos/FreeRTOS.h"
#include "esp_heap_caps.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/event_groups.h"
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
#include "opentelemetry/trace/context.h"

static const char* TAG = "web_server";

static EventGroupHandle_t s_web_server_events;
#define WEB_SERVER_SERVING_BIT BIT0

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

// Each endpoint has its own server, which does all of its work on its own task, so a send that is
// blocked on one endpoint's client cannot delay another endpoint.
struct server_t {
  const char* path;
  uint16_t port;
  uint16_t ctrl_port;
  // 0 keeps the httpd default.
  size_t stack_size;
  httpd_uri_t uri;
  httpd_close_func_t close_fn = nullptr;
  httpd_handle_t handle = nullptr;
};

struct ws_endpoint_t {
  server_t server;
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
  span.SetAttribute("url.path", endpoint.server.path);
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
    ESP_LOGE(TAG, "Invalid WebSocket frame type: %d", ws_pkt.type);
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

  drive_command_t drive_command = {};
  if (parse_drive_command((const char*)ws_pkt.payload, &drive_command)) {
    ESP_LOGI(TAG, "JSON={\"command\": %d, \"value\": %d}", drive_command.command,
             drive_command.value);

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
         {"command.name", static_cast<int64_t>(drive_command.command)},
         {"command.value", static_cast<int64_t>(drive_command.value)}},
        start_opts);
    ws_set_connection_attributes(*span, *endpoint, connection);
    auto scope = opentelemetry::trace::Scope(span);

    // The command queue is a depth-1 mailbox: the latest command wins and this
    // handler never blocks on a full queue.
    if (xQueueOverwrite(g_command_queue, &drive_command) != pdPASS) {
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

// A push endpoint's client only reads, but a frame it sends anyway must still be read off the
// socket: httpd reads only a frame's first byte before calling the handler, and would parse the
// rest as the next frame.
static esp_err_t push_handler(httpd_req_t* req) {
  httpd_ws_frame_t frame = {};
  esp_err_t ret = httpd_ws_recv_frame(req, &frame, 0);
  if (ret != ESP_OK || frame.len == 0) {
    return ret;
  }
  frame.payload = static_cast<uint8_t*>(malloc(frame.len));
  if (frame.payload == nullptr) {
    return ESP_ERR_NO_MEM;
  }
  ret = httpd_ws_recv_frame(req, &frame, frame.len);
  free(frame.payload);
  return ret;
}

static constexpr httpd_uri_t ws_uri(esp_err_t (*handler)(httpd_req_t* req),
                                    ws_endpoint_t* endpoint) {
  return {.uri = nullptr,
          .method = HTTP_GET,
          .handler = handler,
          .user_ctx = endpoint,
          .is_websocket = true,
          .handle_ws_control_frames = false,
          .supported_subprotocol = nullptr,
          .ws_pre_handshake_cb = ws_refuse_if_busy,
          .ws_post_handshake_cb = ws_hand_over};
}

static ws_endpoint_t g_drive{.server = {.path = "/",
                                        .port = WEB_SERVER_DRIVE_PORT,
                                        .ctrl_port = ESP_HTTPD_DEF_CTRL_PORT,
                                        // 8 KB is insufficient for drive_handler with
                                        // tracing_extract + StartSpan.
                                        .stack_size = 16384,
                                        .uri = ws_uri(drive_handler, &g_drive),
                                        .close_fn = ws_close_session}};
static esp_err_t stream_handler(httpd_req_t* req);
static server_t g_camera{.path = "/stream",
                         .port = WEB_SERVER_CAMERA_PORT,
                         .ctrl_port = ESP_HTTPD_DEF_CTRL_PORT + 1,
                         .stack_size = 0,
                         .uri = {.uri = nullptr,
                                 .method = HTTP_GET,
                                 .handler = stream_handler,
                                 .user_ctx = nullptr,
                                 .is_websocket = false,
                                 .handle_ws_control_frames = false,
                                 .supported_subprotocol = nullptr,
                                 .ws_pre_handshake_cb = nullptr,
                                 .ws_post_handshake_cb = nullptr}};
static ws_endpoint_t g_telemetry{.server = {.path = "/telemetry",
                                            .port = WEB_SERVER_TELEMETRY_PORT,
                                            .ctrl_port = ESP_HTTPD_DEF_CTRL_PORT + 2,
                                            .stack_size = 0,
                                            .uri = ws_uri(push_handler, &g_telemetry),
                                            .close_fn = ws_close_session}};
static server_t* const g_servers[] = {&g_drive.server, &g_camera, &g_telemetry.server};

// The Camera endpoint is plain HTTP: one multipart/x-mixed-replace response per client and one
// part per Camera frame (docs/adr/0002-mjpeg-over-http-for-camera-frames.md).
static const char STREAM_CONTENT_TYPE[] = "multipart/x-mixed-replace;boundary=frame";
// W3C Trace Context caps tracestate at 512 characters.
constexpr size_t STREAM_TRACESTATE_MAX = 512;
constexpr size_t STREAM_PART_HEAD_SIZE = 768;
// How often a stream waiting for a frame checks whether the server is stopping.
constexpr int STREAM_FRAME_WAIT_MS = 100;
// httpd's default send timeout, plus a margin for the stream to finish a part.
constexpr int STREAM_RELEASE_TIMEOUT_MS = 7000;

static QueueHandle_t g_frame_queue = NULL;
static QueueHandle_t g_stream_requests = NULL;
// Set by the Camera endpoint's httpd task when it hands a request over, cleared by the stream task
// once it has given the request back.
static std::atomic<bool> g_streaming{false};
static std::atomic<bool> g_stream_stopping{false};

static esp_err_t stream_handler(httpd_req_t* req) {
  if (g_streaming || g_stream_stopping) {
    ESP_LOGW(TAG, "Refusing %s: already serving a connection", req->uri);
    httpd_resp_set_status(req, "503 Service Unavailable");
    httpd_resp_send(req, NULL, 0);
    return ESP_FAIL;
  }
  // The stream task owns the request from here, which leaves this task free to refuse others.
  httpd_req_t* stream_req = nullptr;
  if (httpd_req_async_handler_begin(req, &stream_req) != ESP_OK) {
    ESP_LOGE(TAG, "Could not hand %s over to the stream task", req->uri);
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }
  g_streaming = true;
  xQueueOverwrite(g_stream_requests, &stream_req);
  return ESP_OK;
}

static void stream_set_request_attributes(opentelemetry::trace::Span& span, int fd) {
  socket_address_t server = {};
  socket_address_t client = {};
  ws_read_address(getsockname, fd, &server);
  ws_read_address(getpeername, fd, &client);
  span.SetAttribute("http.request.method", "GET");
  span.SetAttribute("http.route", g_camera.path);
  span.SetAttribute("url.path", g_camera.path);
  span.SetAttribute("url.scheme", "http");
  span.SetAttribute("server.address", server.host);
  span.SetAttribute("server.port", static_cast<int64_t>(server.port));
  span.SetAttribute("client.address", client.host);
  span.SetAttribute("client.port", static_cast<int64_t>(client.port));
  span.SetAttribute("network.transport", "tcp");
  span.SetAttribute("network.protocol.name", "http");
  span.SetAttribute("network.protocol.version", "1.1");
}

static size_t stream_format_part_head(char* head, size_t frame_len,
                                      const trace_headers_t& trace_headers) {
  int len = snprintf(head, STREAM_PART_HEAD_SIZE,
                     "\r\n--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n",
                     static_cast<unsigned>(frame_len));
  if (!trace_headers.traceparent.empty()) {
    len += snprintf(head + len, STREAM_PART_HEAD_SIZE - len, "traceparent: %s\r\n",
                    trace_headers.traceparent.c_str());
  }
  if (!trace_headers.tracestate.empty() &&
      trace_headers.tracestate.size() <= STREAM_TRACESTATE_MAX) {
    len += snprintf(head + len, STREAM_PART_HEAD_SIZE - len, "tracestate: %s\r\n",
                    trace_headers.tracestate.c_str());
  }
  len += snprintf(head + len, STREAM_PART_HEAD_SIZE - len, "\r\n");
  return len;
}

// Sends the frame straight from its frame buffer; false once the client has gone.
static bool stream_send_part(httpd_req_t* req, const camera_fb_t& frame,
                             const opentelemetry::trace::Span& request_span) {
  opentelemetry::trace::StartSpanOptions send_opts;
  send_opts.kind = opentelemetry::trace::SpanKind::kProducer;
  send_opts.parent = request_span.GetContext();
  auto span = esp_opentelemetry_tracer()->StartSpan(
      "camera.frame.send", {{"camera.frame.size", static_cast<int64_t>(frame.len)}}, send_opts);
  auto scope = opentelemetry::trace::Scope(span);

  char head[STREAM_PART_HEAD_SIZE];
  size_t head_len = stream_format_part_head(head, frame.len, tracing_headers());
  span->SetAttribute("camera.part.size", static_cast<int64_t>(head_len + frame.len));
  esp_err_t err = httpd_resp_send_chunk(req, head, head_len);
  if (err == ESP_OK) {
    err = httpd_resp_send_chunk(req, reinterpret_cast<const char*>(frame.buf), frame.len);
  }
  if (err != ESP_OK) {
    span->SetStatus(opentelemetry::trace::StatusCode::kError, "send failed");
  }
  span->End();
  return err == ESP_OK;
}

static void stream_serve(httpd_req_t* req) {
  opentelemetry::trace::StartSpanOptions request_opts;
  request_opts.kind = opentelemetry::trace::SpanKind::kServer;
  auto request_span = esp_opentelemetry_tracer()->StartSpan("GET /stream", request_opts);
  stream_set_request_attributes(*request_span, httpd_req_to_sockfd(req));
  request_span->SetAttribute("http.response.status_code", static_cast<int64_t>(200));
  httpd_resp_set_type(req, STREAM_CONTENT_TYPE);

  camera_start();
  ESP_LOGI(TAG, "Stream started");
  while (!g_stream_stopping) {
    camera_fb_t* frame = nullptr;
    if (xQueueReceive(g_frame_queue, &frame, pdMS_TO_TICKS(STREAM_FRAME_WAIT_MS)) != pdPASS) {
      continue;
    }
    bool sent = stream_send_part(req, *frame, *request_span);
    esp_camera_fb_return(frame);
    if (!sent) {
      break;
    }
    web_server_metrics_update();
  }
  camera_stop();
  ESP_LOGI(TAG, "Stream stopped");
  request_span->End();
}

void stream_task(void* p) {
  ESP_LOGI(TAG, "Starting stream task");
  while (true) {
    httpd_req_t* req = nullptr;
    if (xQueueReceive(g_stream_requests, &req, portMAX_DELAY) != pdPASS) {
      continue;
    }
    if (!g_stream_stopping) {
      stream_serve(req);
    }
    // The stream's response is never finished, so its connection ends with it.
    httpd_handle_t hd = req->handle;
    int fd = httpd_req_to_sockfd(req);
    httpd_req_async_handler_complete(req);
    httpd_sess_trigger_close(hd, fd);
    g_streaming = false;
  }
}

// httpd_stop() frees the server a handed-over request points into, so the stream gives its request
// back first.
static void stream_release() {
  g_stream_stopping = true;
  const int poll_interval_ms = 10;
  TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(STREAM_RELEASE_TIMEOUT_MS);
  while (g_streaming) {
    if (xTaskGetTickCount() > deadline) {
      ESP_LOGE(TAG, "The stream did not stop in time");
      return;
    }
    vTaskDelay(pdMS_TO_TICKS(poll_interval_ms));
  }
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

    telemetry_reading_t reading = {};
    if (!ws_wait_for_item(g_telemetry, connection, &reading)) {
      teardown();
      continue;
    }
    if (!ws_connection_is_live(connection)) {
      teardown();
      continue;
    }

    cJSON* message_json = convert_telemetry_reading_to_json(reading);

    opentelemetry::trace::StartSpanOptions send_opts;
    send_opts.kind = opentelemetry::trace::SpanKind::kProducer;
    send_opts.parent = connection_span->GetContext();
    auto send_span = esp_opentelemetry_tracer()->StartSpan(
        "ws.telemetry.send", {{"ws.message.type", "telemetry"}}, send_opts);
    ws_set_connection_attributes(*send_span, g_telemetry, connection);
    auto send_scope = opentelemetry::trace::Scope(send_span);
    tracing_inject(message_json);

    char* message_json_str = cJSON_PrintUnformatted(message_json);
    cJSON_Delete(message_json);
    size_t payload_len = strlen(message_json_str);
    send_span->SetAttribute("ws.message.size", static_cast<int64_t>(payload_len));

    uint32_t seq = 0;
    esp_err_t ret = ws_queue_send(g_telemetry, connection, message_json_str, payload_len, &seq);
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
static void keep_user_ctx(void* ctx) { (void)ctx; }

static esp_err_t start_server(server_t& server) {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = server.port;
  config.ctrl_port = server.ctrl_port;
  // The owner and one connection being refused. With LRU purge on, that connection would evict the
  // owner before the refusal runs.
  config.max_open_sockets = 2;
  config.lru_purge_enable = false;
  if (server.stack_size != 0) {
    config.stack_size = server.stack_size;
  }
  config.global_user_ctx = server.uri.user_ctx;
  config.global_user_ctx_free_fn = keep_user_ctx;
  config.close_fn = server.close_fn;

  ESP_LOGI(TAG, "Starting the %s server on port %d", server.path, server.port);
  esp_err_t err = httpd_start(&server.handle, &config);
  if (err != ESP_OK) {
    server.handle = nullptr;
    return err;
  }
  httpd_uri_t uri = server.uri;
  uri.uri = server.path;
  return httpd_register_uri_handler(server.handle, &uri);
}

static void stop_web_servers() {
  xEventGroupClearBits(s_web_server_events, WEB_SERVER_SERVING_BIT);
  stream_release();
  for (server_t* server : g_servers) {
    if (server->handle == nullptr) {
      continue;
    }
    ESP_LOGI(TAG, "Stopping the %s server", server->path);
    if (httpd_stop(server->handle) != ESP_OK) {
      ESP_LOGE(TAG, "Failed to stop the %s server", server->path);
      continue;
    }
    server->handle = nullptr;
  }
  g_stream_stopping = false;
}

// Starts every server that is not running. The servers run all together or not at all, so a
// server that fails to start stops the others.
static void start_web_servers() {
  bool started = false;
  for (server_t* server : g_servers) {
    if (server->handle != nullptr) {
      continue;
    }
    esp_err_t err = start_server(*server);
    if (err != ESP_OK) {
      ESP_LOGE(TAG, "Error starting the %s server: %s", server->path, esp_err_to_name(err));
      stop_web_servers();
      return;
    }
    started = true;
  }
  if (started) {
    ESP_LOGI(TAG, "Serving every endpoint");
  }
  xEventGroupSetBits(s_web_server_events, WEB_SERVER_SERVING_BIT);
}

void web_server_wait_for_serving() {
  xEventGroupWaitBits(s_web_server_events, WEB_SERVER_SERVING_BIT, pdFALSE, pdFALSE, portMAX_DELAY);
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
  s_web_server_events = xEventGroupCreate();
  g_command_queue = command_queue;
  g_frame_queue = frame_queue;
  g_stream_requests = xQueueCreate(1, sizeof(httpd_req_t*));
  ws_endpoint_init(g_telemetry, telemetry_queue);

  // Both stacks live in PSRAM to spare internal RAM.
  constexpr UBaseType_t stack_caps = MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT;
  if (xTaskCreateWithCaps(stream_task, "stream_task", 12288, nullptr, 1, nullptr, stack_caps) !=
      pdPASS) {
    ESP_LOGE(TAG, "xTaskCreate(stream_task) failed - no PSRAM");
    return;
  }
  if (xTaskCreateWithCaps(ws_telemetry_task, "ws_telemetry_task", 32768, nullptr, 1, nullptr,
                          stack_caps) != pdPASS) {
    ESP_LOGE(TAG, "xTaskCreate(ws_telemetry_task) failed - no PSRAM");
    return;
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
