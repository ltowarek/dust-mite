#include <atomic>
#include <iterator>
#include "esp_websocket_client.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "unity.h"

static const int OPEN_TIMEOUT_MS = 8000;
static const int CLOSE_TIMEOUT_MS = 10000;
static const int CLOSE_BUDGET_MS = 2000;
static const int FIRST_FRAME_BUDGET_MS = 2000;
static const int HTTP_SERVICE_UNAVAILABLE = 503;

enum : EventBits_t {
  WS_OPENED = BIT0,
  WS_REFUSED = BIT1,
  WS_CLOSE_REPLIED = BIT2,
  WS_DISCONNECTED = BIT3,
  WS_CLOSE_DONE = BIT4,
};

struct ws_client_t {
  esp_websocket_client_handle_t handle;
  EventGroupHandle_t events;
  std::atomic<int> handshake_status;
  std::atomic<int> messages;
  std::atomic<int> malformed;
};

static void ws_client_on_event(void* arg, esp_event_base_t base, int32_t id, void* data) {
  auto* client = static_cast<ws_client_t*>(arg);
  auto* event = static_cast<esp_websocket_event_data_t*>(data);
  switch (id) {
    case WEBSOCKET_EVENT_CONNECTED:
      xEventGroupSetBits(client->events, WS_OPENED);
      break;
    case WEBSOCKET_EVENT_ERROR:
      if (event->error_handle.esp_ws_handshake_status_code != 0) {
        client->handshake_status = event->error_handle.esp_ws_handshake_status_code;
        xEventGroupSetBits(client->events, WS_REFUSED);
      }
      break;
    case WEBSOCKET_EVENT_DISCONNECTED:
      xEventGroupSetBits(client->events, WS_DISCONNECTED);
      break;
    case WEBSOCKET_EVENT_DATA: {
      if (event->op_code == WS_TRANSPORT_OPCODES_CLOSE) {
        xEventGroupSetBits(client->events, WS_CLOSE_REPLIED);
        break;
      }
      if (event->op_code != WS_TRANSPORT_OPCODES_TEXT) {
        break;
      }
      if (event->payload_offset == 0 && (event->data_len == 0 || event->data_ptr[0] != '{')) {
        client->malformed++;
      }
      if (event->payload_offset + event->data_len < event->payload_len) {
        break;
      }
      if (event->data_len == 0 || event->data_ptr[event->data_len - 1] != '}') {
        client->malformed++;
      }
      client->messages++;
      break;
    }
    default:
      break;
  }
}

static ws_client_t* ws_connect(const char* path, size_t ping_interval_sec = 0) {
  auto* client = new ws_client_t{};
  client->events = xEventGroupCreate();

  esp_websocket_client_config_t config = {};
  config.host = "127.0.0.1";
  config.port = 80;
  config.path = path;
  config.disable_auto_reconnect = true;
  config.network_timeout_ms = OPEN_TIMEOUT_MS;
  config.ping_interval_sec = ping_interval_sec;
  config.pingpong_timeout_sec = ping_interval_sec * 3;
  client->handle = esp_websocket_client_init(&config);
  esp_websocket_register_events(client->handle, WEBSOCKET_EVENT_ANY, ws_client_on_event, client);
  esp_websocket_client_start(client->handle);

  xEventGroupWaitBits(client->events, WS_OPENED | WS_REFUSED | WS_DISCONNECTED, pdFALSE, pdFALSE,
                      pdMS_TO_TICKS(OPEN_TIMEOUT_MS));
  return client;
}

static bool ws_is_open(ws_client_t* client) {
  return xEventGroupGetBits(client->events) & WS_OPENED;
}

static void ws_destroy(ws_client_t* client) {
  esp_websocket_client_destroy(client->handle);
  vEventGroupDelete(client->events);
  delete client;
}

static ws_client_t* ws_connect_or_fail(const char* path) {
  ws_client_t* client = ws_connect(path);
  if (!ws_is_open(client)) {
    TEST_FAIL_MESSAGE("connection was not opened");
  }
  return client;
}

// Each endpoint serves one connection and refuses others with 503, so a reconnect retries until
// the server has processed the previous connection's close.
static ws_client_t* ws_try_connect_when_free(const char* path) {
  const int busy_retry_interval_ms = 100;
  TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(CLOSE_TIMEOUT_MS);
  for (int attempt = 0;; ++attempt) {
    ws_client_t* client = ws_connect(path);
    if (ws_is_open(client)) {
      return client;
    }
    int status = client->handshake_status;
    ws_destroy(client);
    if (status != HTTP_SERVICE_UNAVAILABLE || xTaskGetTickCount() > deadline) {
      return nullptr;
    }
    vTaskDelay(pdMS_TO_TICKS(busy_retry_interval_ms));
  }
}

static ws_client_t* ws_connect_when_free(const char* path) {
  ws_client_t* client = ws_try_connect_when_free(path);
  if (client == nullptr) {
    TEST_FAIL_MESSAGE("connection was not opened once the endpoint was free");
  }
  return client;
}

static bool ws_wait_for_messages(ws_client_t* client, int count, int timeout_ms) {
  const int poll_interval_ms = 10;
  TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(timeout_ms);
  while (client->messages < count) {
    if (xTaskGetTickCount() > deadline) {
      return false;
    }
    vTaskDelay(pdMS_TO_TICKS(poll_interval_ms));
  }
  return true;
}

static void ws_wait_for_messages_or_fail(ws_client_t* client, int count) {
  const int messages_timeout_ms = 8000;
  if (!ws_wait_for_messages(client, count, messages_timeout_ms)) {
    TEST_FAIL_MESSAGE("messages were not received");
  }
}

static void ws_close_task(void* arg) {
  auto* client = static_cast<ws_client_t*>(arg);
  esp_websocket_client_close(client->handle, pdMS_TO_TICKS(CLOSE_TIMEOUT_MS));
  xEventGroupSetBits(client->events, WS_CLOSE_DONE);
  vTaskDelete(NULL);
}

// The close runs on its own task, so a test can report a close that does not finish instead of
// hanging on it.
static void ws_close_in_background(ws_client_t* client) {
  xTaskCreate(ws_close_task, "ws_close", 4096, client, 5, nullptr);
}

static bool ws_wait_for_close(ws_client_t* client, int timeout_ms) {
  EventBits_t bits = xEventGroupWaitBits(client->events, WS_CLOSE_DONE, pdFALSE, pdFALSE,
                                         pdMS_TO_TICKS(timeout_ms));
  return bits & WS_CLOSE_DONE;
}

static bool ws_wait_for_close_reply(ws_client_t* client, int timeout_ms) {
  EventBits_t bits = xEventGroupWaitBits(client->events, WS_CLOSE_REPLIED, pdFALSE, pdFALSE,
                                         pdMS_TO_TICKS(timeout_ms));
  return bits & WS_CLOSE_REPLIED;
}

TEST_CASE("stream_close_handshake_completes_promptly", "[web_server]") {
  ws_client_t* ws = ws_connect_or_fail("/stream");
  ws_wait_for_messages_or_fail(ws, 5);

  ws_close_in_background(ws);

  TEST_ASSERT_TRUE_MESSAGE(ws_wait_for_close_reply(ws, CLOSE_BUDGET_MS),
                           "server did not reply to CLOSE in time; the streaming task is not "
                           "servicing inbound frames");
}

TEST_CASE("stream_reconnect_receives_data_while_previous_closes", "[web_server]") {
  ws_client_t* first = ws_connect_or_fail("/stream");
  ws_wait_for_messages_or_fail(first, 5);
  ws_close_in_background(first);

  ws_client_t* second = ws_connect_when_free("/stream");

  TEST_ASSERT_TRUE_MESSAGE(ws_wait_for_messages(second, 1, FIRST_FRAME_BUDGET_MS),
                           "reconnected /stream produced no frame");
}

static const int REPEATED_CONNECTION_COUNT = 6;

// Fills closing with the connections that were opened, and returns how many there are.
static int connect_and_close_stream_repeatedly(ws_client_t* closing[]) {
  int closing_count = 0;
  for (int i = 0; i < REPEATED_CONNECTION_COUNT; ++i) {
    ws_client_t* ws = ws_connect("/stream");
    if (ws_is_open(ws)) {
      closing[closing_count++] = ws;
      ws_close_in_background(ws);
      continue;
    }
    if (ws->handshake_status != HTTP_SERVICE_UNAVAILABLE) {
      TEST_FAIL_MESSAGE("a repeated /stream connection was refused with a status other than 503");
    }
    ws_destroy(ws);
  }
  return closing_count;
}

TEST_CASE("stream_serves_frames_after_repeated_connect_and_close", "[web_server]") {
  ws_client_t* closing[REPEATED_CONNECTION_COUNT];
  connect_and_close_stream_repeatedly(closing);

  ws_client_t* ws = ws_connect_when_free("/stream");

  TEST_ASSERT_TRUE_MESSAGE(ws_wait_for_messages(ws, 1, FIRST_FRAME_BUDGET_MS),
                           "no frame after repeated connect and close");
}

TEST_CASE("stream_replies_to_close_of_every_repeated_connection", "[web_server]") {
  ws_client_t* closing[REPEATED_CONNECTION_COUNT];
  int closing_count = connect_and_close_stream_repeatedly(closing);

  int unanswered = 0;
  for (int i = 0; i < closing_count; ++i) {
    ws_client_t* ws = closing[i];
    if (!ws_wait_for_close(ws, CLOSE_TIMEOUT_MS + CLOSE_BUDGET_MS)) {
      TEST_FAIL_MESSAGE("a repeated /stream connection did not finish closing");
    }
    if (!(xEventGroupGetBits(ws->events) & WS_CLOSE_REPLIED)) {
      ++unanswered;
    }
  }

  TEST_ASSERT_EQUAL_INT_MESSAGE(0, unanswered,
                                "repeated /stream connections were dropped without a CLOSE reply");
}

TEST_CASE("stream_recovers_after_lru_purge", "[web_server]") {
  const char* paths[] = {"/", "/telemetry", "/stream", "/"};
  ws_client_t* held[std::size(paths)];
  for (size_t i = 0; i < std::size(paths); ++i) {
    held[i] = ws_connect_or_fail(paths[i]);
  }
  for (ws_client_t* ws : held) {
    ws_close_in_background(ws);
  }

  ws_client_t* ws = ws_connect_when_free("/stream");

  TEST_ASSERT_TRUE_MESSAGE(ws_wait_for_messages(ws, 1, FIRST_FRAME_BUDGET_MS),
                           "no frame after an LRU purge");
}

TEST_CASE("stream_answers_ping_mid_stream", "[web_server]") {
  const size_t ping_interval_sec = 2;
  const int stream_duration_ms = 10000;
  ws_client_t* ws = ws_connect("/stream", ping_interval_sec);
  if (!ws_is_open(ws)) {
    TEST_FAIL_MESSAGE("connection was not opened");
  }

  EventBits_t bits = xEventGroupWaitBits(ws->events, WS_DISCONNECTED, pdFALSE, pdFALSE,
                                         pdMS_TO_TICKS(stream_duration_ms));
  if (bits & WS_DISCONNECTED) {
    TEST_FAIL_MESSAGE("connection dropped; pings were not answered");
  }
  if (ws->malformed > 0) {
    TEST_FAIL_MESSAGE("a frame was malformed");
  }

  TEST_ASSERT_GREATER_THAN_INT_MESSAGE(0, ws->messages, "no frames received");
}

static int refuse_second_connections(const char* path) {
  const int attempts = 2;
  int refused = 0;
  for (int i = 0; i < attempts; ++i) {
    ws_client_t* second = ws_connect(path);
    if (second->handshake_status == HTTP_SERVICE_UNAVAILABLE) {
      ++refused;
    }
    ws_destroy(second);
  }
  return refused;
}

static void second_connection_refused_before_upgrade(const char* path) {
  ws_connect_or_fail(path);

  TEST_ASSERT_EQUAL_INT_MESSAGE(2, refuse_second_connections(path),
                                "a second connection was not refused with 503");
}

static void served_again_after_refusing_second_connection(const char* path) {
  ws_client_t* served = ws_connect_or_fail(path);
  refuse_second_connections(path);
  ws_close_in_background(served);
  if (!ws_wait_for_close(served, CLOSE_TIMEOUT_MS + CLOSE_BUDGET_MS)) {
    TEST_FAIL_MESSAGE("served connection close did not finish");
  }

  TEST_ASSERT_NOT_NULL_MESSAGE(ws_try_connect_when_free(path),
                               "endpoint did not accept a connection after its served one closed");
}

TEST_CASE("stream_second_connection_refused_before_upgrade", "[web_server]") {
  second_connection_refused_before_upgrade("/stream");
}

TEST_CASE("telemetry_second_connection_refused_before_upgrade", "[web_server]") {
  second_connection_refused_before_upgrade("/telemetry");
}

TEST_CASE("stream_served_again_after_refusing_second_connection", "[web_server]") {
  served_again_after_refusing_second_connection("/stream");
}

TEST_CASE("telemetry_served_again_after_refusing_second_connection", "[web_server]") {
  served_again_after_refusing_second_connection("/telemetry");
}
