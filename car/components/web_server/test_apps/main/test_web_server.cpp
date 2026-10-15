#include <atomic>
#include <cstring>
#include <iterator>
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_websocket_client.h"
#include "esp_wifi_types.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "lwip/sockets.h"
#include "motor.hpp"
#include "test_app.hpp"
#include "unity.h"
#include "web_server.hpp"

static const int OPEN_TIMEOUT_MS = 8000;
static const int CLOSE_TIMEOUT_MS = 10000;
static const int CLOSE_BUDGET_MS = 2000;
static const int FIRST_FRAME_BUDGET_MS = 2000;
static const int HTTP_NOT_FOUND = 404;
static const int HTTP_SERVICE_UNAVAILABLE = 503;

struct endpoint_t {
  uint16_t port;
  const char* path;
};

static const endpoint_t DRIVE = {WEB_SERVER_DRIVE_PORT, "/"};
static const endpoint_t CAMERA = {WEB_SERVER_CAMERA_PORT, "/stream"};
static const endpoint_t TELEMETRY = {WEB_SERVER_TELEMETRY_PORT, "/telemetry"};
static const endpoint_t ENDPOINTS[] = {DRIVE, CAMERA, TELEMETRY};

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

static ws_client_t* ws_connect(const endpoint_t& endpoint, size_t ping_interval_sec = 0) {
  auto* client = new ws_client_t{};
  client->events = xEventGroupCreate();

  esp_websocket_client_config_t config = {};
  config.host = "127.0.0.1";
  config.port = endpoint.port;
  config.path = endpoint.path;
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

static ws_client_t* ws_connect_or_fail(const endpoint_t& endpoint) {
  ws_client_t* client = ws_connect(endpoint);
  if (!ws_is_open(client)) {
    TEST_FAIL_MESSAGE("connection was not opened");
  }
  return client;
}

// Each endpoint serves one connection and refuses others with 503, so a reconnect retries until
// the server has processed the previous connection's close.
static ws_client_t* ws_try_connect_when_free(const endpoint_t& endpoint) {
  const int busy_retry_interval_ms = 100;
  TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(CLOSE_TIMEOUT_MS);
  for (int attempt = 0;; ++attempt) {
    ws_client_t* client = ws_connect(endpoint);
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

static ws_client_t* ws_connect_when_free(const endpoint_t& endpoint) {
  ws_client_t* client = ws_try_connect_when_free(endpoint);
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
  ws_client_t* ws = ws_connect_or_fail(CAMERA);
  ws_wait_for_messages_or_fail(ws, 5);

  ws_close_in_background(ws);

  TEST_ASSERT_TRUE_MESSAGE(ws_wait_for_close_reply(ws, CLOSE_BUDGET_MS),
                           "server did not reply to CLOSE in time; the streaming task is not "
                           "servicing inbound frames");
}

TEST_CASE("stream_reconnect_receives_data_while_previous_closes", "[web_server]") {
  ws_client_t* first = ws_connect_or_fail(CAMERA);
  ws_wait_for_messages_or_fail(first, 5);
  ws_close_in_background(first);

  ws_client_t* second = ws_connect_when_free(CAMERA);

  TEST_ASSERT_TRUE_MESSAGE(ws_wait_for_messages(second, 1, FIRST_FRAME_BUDGET_MS),
                           "reconnected /stream produced no frame");
}

static const int REPEATED_CONNECTION_COUNT = 6;

// Fills closing with the connections that were opened, and returns how many there are.
static int connect_and_close_stream_repeatedly(ws_client_t* closing[]) {
  int closing_count = 0;
  for (int i = 0; i < REPEATED_CONNECTION_COUNT; ++i) {
    ws_client_t* ws = ws_connect(CAMERA);
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

  ws_client_t* ws = ws_connect_when_free(CAMERA);

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

TEST_CASE("camera_serves_frames_while_drive_and_telemetry_are_held", "[web_server]") {
  ws_connect_or_fail(DRIVE);
  ws_connect_or_fail(TELEMETRY);

  ws_client_t* ws = ws_connect_or_fail(CAMERA);

  TEST_ASSERT_TRUE_MESSAGE(ws_wait_for_messages(ws, 1, FIRST_FRAME_BUDGET_MS),
                           "no frame while the other endpoints were held");
}

TEST_CASE("stream_answers_ping_mid_stream", "[web_server]") {
  const size_t ping_interval_sec = 2;
  const int stream_duration_ms = 10000;
  ws_client_t* ws = ws_connect(CAMERA, ping_interval_sec);
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

static int refuse_second_connections(const endpoint_t& endpoint) {
  const int attempts = 2;
  int refused = 0;
  for (int i = 0; i < attempts; ++i) {
    ws_client_t* second = ws_connect(endpoint);
    if (second->handshake_status == HTTP_SERVICE_UNAVAILABLE) {
      ++refused;
    }
    ws_destroy(second);
  }
  return refused;
}

static void second_connection_refused_before_upgrade(const endpoint_t& endpoint) {
  ws_connect_or_fail(endpoint);

  TEST_ASSERT_EQUAL_INT_MESSAGE(2, refuse_second_connections(endpoint),
                                "a second connection was not refused with 503");
}

static void served_again_after_refusing_second_connection(const endpoint_t& endpoint) {
  ws_client_t* served = ws_connect_or_fail(endpoint);
  refuse_second_connections(endpoint);
  ws_close_in_background(served);
  if (!ws_wait_for_close(served, CLOSE_TIMEOUT_MS + CLOSE_BUDGET_MS)) {
    TEST_FAIL_MESSAGE("served connection close did not finish");
  }

  TEST_ASSERT_NOT_NULL_MESSAGE(ws_try_connect_when_free(endpoint),
                               "endpoint did not accept a connection after its served one closed");
}

TEST_CASE("drive_second_connection_refused_before_upgrade", "[web_server]") {
  second_connection_refused_before_upgrade(DRIVE);
}

TEST_CASE("stream_second_connection_refused_before_upgrade", "[web_server]") {
  second_connection_refused_before_upgrade(CAMERA);
}

TEST_CASE("telemetry_second_connection_refused_before_upgrade", "[web_server]") {
  second_connection_refused_before_upgrade(TELEMETRY);
}

TEST_CASE("drive_served_again_after_refusing_second_connection", "[web_server]") {
  served_again_after_refusing_second_connection(DRIVE);
}

TEST_CASE("stream_served_again_after_refusing_second_connection", "[web_server]") {
  served_again_after_refusing_second_connection(CAMERA);
}

TEST_CASE("telemetry_served_again_after_refusing_second_connection", "[web_server]") {
  served_again_after_refusing_second_connection(TELEMETRY);
}

static int handshake_status_of(const endpoint_t& endpoint) {
  ws_client_t* ws = ws_connect(endpoint);
  int status = ws->handshake_status;
  ws_destroy(ws);
  return status;
}

TEST_CASE("telemetry_path_on_drive_port_is_not_found", "[web_server]") {
  TEST_ASSERT_EQUAL_INT(HTTP_NOT_FOUND, handshake_status_of({DRIVE.port, TELEMETRY.path}));
}

TEST_CASE("drive_path_on_camera_port_is_not_found", "[web_server]") {
  TEST_ASSERT_EQUAL_INT(HTTP_NOT_FOUND, handshake_status_of({CAMERA.port, DRIVE.path}));
}

TEST_CASE("camera_path_on_telemetry_port_is_not_found", "[web_server]") {
  TEST_ASSERT_EQUAL_INT(HTTP_NOT_FOUND, handshake_status_of({TELEMETRY.port, CAMERA.path}));
}

static const int COMMAND_TIMEOUT_MS = 2000;
static const char BRAKE_50[] = "{\"command\": 3, \"value\": 50}";

static bool command_received(drive_command_t* drive_command) {
  return xQueueReceive(test_app_command_queue, drive_command, pdMS_TO_TICKS(COMMAND_TIMEOUT_MS)) ==
         pdPASS;
}

TEST_CASE("command_reaches_the_command_queue", "[web_server]") {
  ws_client_t* ws = ws_connect_or_fail(DRIVE);
  esp_websocket_client_send_text(ws->handle, BRAKE_50, strlen(BRAKE_50), portMAX_DELAY);

  drive_command_t received = {};
  if (!command_received(&received)) {
    TEST_FAIL_MESSAGE("no command reached the command queue");
  }

  TEST_ASSERT_EQUAL_INT(50, received.value);
}

TEST_CASE("command_that_is_not_json_is_dropped", "[web_server]") {
  const char not_json[] = "{not json";
  ws_client_t* ws = ws_connect_or_fail(DRIVE);
  esp_websocket_client_send_text(ws->handle, not_json, strlen(not_json), portMAX_DELAY);

  drive_command_t received = {};
  TEST_ASSERT_FALSE_MESSAGE(command_received(&received), "a malformed command was queued");
}

TEST_CASE("command_in_a_binary_frame_is_dropped", "[web_server]") {
  ws_client_t* ws = ws_connect_or_fail(DRIVE);
  esp_websocket_client_send_bin(ws->handle, BRAKE_50, strlen(BRAKE_50), portMAX_DELAY);

  drive_command_t received = {};
  TEST_ASSERT_FALSE_MESSAGE(command_received(&received), "a binary frame was queued");
}

// A server that refuses a second connection with 503 is still running.
static bool endpoint_answers(const endpoint_t& endpoint) {
  ws_client_t* ws = ws_connect(endpoint);
  bool answered = ws_is_open(ws) || ws->handshake_status != 0;
  ws_destroy(ws);
  return answered;
}

static int count_answering_endpoints() {
  int answering = 0;
  for (const endpoint_t& endpoint : ENDPOINTS) {
    if (endpoint_answers(endpoint)) {
      ++answering;
    }
  }
  return answering;
}

static bool wait_until_answering_endpoints(int count, int timeout_ms) {
  const int poll_interval_ms = 100;
  TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(timeout_ms);
  while (count_answering_endpoints() != count) {
    if (xTaskGetTickCount() > deadline) {
      return false;
    }
    vTaskDelay(pdMS_TO_TICKS(poll_interval_ms));
  }
  return true;
}

static void post_wifi_disconnected() {
  wifi_event_sta_disconnected_t event = {};
  esp_event_post(WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED, &event, sizeof(event), portMAX_DELAY);
}

static void stop_servers_or_fail() {
  post_wifi_disconnected();
  if (!wait_until_answering_endpoints(0, CLOSE_TIMEOUT_MS)) {
    TEST_FAIL_MESSAGE("servers did not stop after Wi-Fi disconnected");
  }
}

static void got_ip_handled(void* arg, esp_event_base_t base, int32_t id, void* data) {
  xSemaphoreGive(static_cast<SemaphoreHandle_t>(arg));
}

// Handlers of one event run in registration order on the default event loop's task, so a handler
// registered here runs after the web server's has finished.
static void post_got_ip_and_wait_until_handled() {
  SemaphoreHandle_t handled = xSemaphoreCreateBinary();
  esp_event_handler_instance_t instance = nullptr;
  esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, got_ip_handled, handled,
                                      &instance);
  ip_event_got_ip_t event = {};
  event.esp_netif = esp_netif_get_default_netif();
  esp_netif_get_ip_info(event.esp_netif, &event.ip_info);
  esp_event_post(IP_EVENT, IP_EVENT_STA_GOT_IP, &event, sizeof(event), portMAX_DELAY);
  xSemaphoreTake(handled, pdMS_TO_TICKS(CLOSE_TIMEOUT_MS));
  esp_event_handler_instance_unregister(IP_EVENT, IP_EVENT_STA_GOT_IP, instance);
  vSemaphoreDelete(handled);
}

TEST_CASE("servers_stop_when_wifi_disconnects", "[web_server]") {
  post_wifi_disconnected();

  TEST_ASSERT_TRUE_MESSAGE(wait_until_answering_endpoints(0, CLOSE_TIMEOUT_MS),
                           "an endpoint still answers after Wi-Fi disconnected");
}

TEST_CASE("servers_start_again_when_wifi_gets_an_ip", "[web_server]") {
  stop_servers_or_fail();

  post_got_ip_and_wait_until_handled();

  TEST_ASSERT_EQUAL_INT_MESSAGE(std::size(ENDPOINTS), count_answering_endpoints(),
                                "not every endpoint answers after Wi-Fi got an IP");
}

// The probes leave connections to the port in TIME_WAIT, which only SO_REUSEADDR binds past. lwIP
// still lets one socket at a time listen on the port, so the server's own listen fails.
static int listen_on(uint16_t port) {
  int fd = socket(AF_INET6, SOCK_STREAM, 0);
  int reuse = 1;
  setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
  sockaddr_in6 address = {};
  address.sin6_family = AF_INET6;
  address.sin6_port = htons(port);
  address.sin6_addr = in6addr_any;
  if (bind(fd, reinterpret_cast<sockaddr*>(&address), sizeof(address)) != 0 || listen(fd, 1) != 0) {
    close(fd);
    return -1;
  }
  return fd;
}

TEST_CASE("no_server_runs_when_one_fails_to_start", "[web_server]") {
  stop_servers_or_fail();
  int blocker = listen_on(TELEMETRY.port);
  if (blocker < 0) {
    TEST_FAIL_MESSAGE("could not take the telemetry port");
  }

  post_got_ip_and_wait_until_handled();
  close(blocker);

  TEST_ASSERT_EQUAL_INT_MESSAGE(0, count_answering_endpoints(),
                                "servers kept running after another one failed to start");
}

TEST_CASE("served_connection_survives_wifi_getting_an_ip_again", "[web_server]") {
  ws_client_t* ws = ws_connect_or_fail(CAMERA);
  ws_wait_for_messages_or_fail(ws, 1);

  post_got_ip_and_wait_until_handled();
  int received = ws->messages;

  TEST_ASSERT_TRUE_MESSAGE(ws_wait_for_messages(ws, received + 1, FIRST_FRAME_BUDGET_MS),
                           "the served connection stopped after Wi-Fi got an IP again");
}

static void keeps_sending_after_a_client_frame(const endpoint_t& endpoint) {
  const char hello[] = "hello";
  ws_client_t* ws = ws_connect_or_fail(endpoint);
  ws_wait_for_messages_or_fail(ws, 1);

  esp_websocket_client_send_text(ws->handle, hello, strlen(hello), portMAX_DELAY);
  int received = ws->messages;

  TEST_ASSERT_TRUE_MESSAGE(ws_wait_for_messages(ws, received + 2, CLOSE_TIMEOUT_MS),
                           "the endpoint stopped sending after the client sent a frame");
}

TEST_CASE("camera_keeps_sending_after_a_client_frame", "[web_server]") {
  keeps_sending_after_a_client_frame(CAMERA);
}

TEST_CASE("telemetry_keeps_sending_after_a_client_frame", "[web_server]") {
  keeps_sending_after_a_client_frame(TELEMETRY);
}
