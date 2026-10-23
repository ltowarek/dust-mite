#include "stream_client.hpp"

#include <cerrno>
#include <cstdio>
#include <cstring>
#include "freertos/task.h"
#include "lwip/sockets.h"
#include "unity.h"

static const char STREAM_PART_START[] = "--frame\r\n";
static const int STREAM_READ_TIMEOUT_MS = 1000;

int http_connect(uint16_t port) {
  int fd = socket(AF_INET, SOCK_STREAM, 0);
  timeval timeout = {.tv_sec = STREAM_READ_TIMEOUT_MS / 1000, .tv_usec = 0};
  setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
  setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
  sockaddr_in address = {};
  address.sin_family = AF_INET;
  address.sin_port = htons(port);
  address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  if (connect(fd, reinterpret_cast<sockaddr*>(&address), sizeof(address)) != 0) {
    close(fd);
    return -1;
  }
  return fd;
}

int http_get(int fd, const char* path, char* head, size_t head_size) {
  char request[96];
  int len = snprintf(request, sizeof(request), "GET %s HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n", path);
  if (send(fd, request, len, 0) != len) {
    return 0;
  }
  size_t used = 0;
  TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(OPEN_TIMEOUT_MS);
  while (used + 1 < head_size && xTaskGetTickCount() < deadline) {
    if (recv(fd, head + used, 1, 0) != 1) {
      continue;
    }
    head[++used] = '\0';
    if (used >= 4 && strcmp(head + used - 4, "\r\n\r\n") == 0) {
      int status = 0;
      return sscanf(head, "HTTP/1.1 %d", &status) == 1 ? status : 0;
    }
  }
  return 0;
}

static void copy_header(const char* head, const char* name, char* out, size_t out_size) {
  const char* value = strstr(head, name);
  if (value == nullptr) {
    return;
  }
  value += strlen(name);
  size_t len = strcspn(value, "\r");
  snprintf(out, out_size, "%.*s", static_cast<int>(len), value);
}

// Counts the matches of pattern that end in the newly read bytes, which follow carried bytes.
static int count_new_matches(const char* window, size_t carried, size_t len, const char* pattern) {
  size_t pattern_len = strlen(pattern);
  int matches = 0;
  for (size_t i = 0; i + pattern_len <= len; ++i) {
    if (i + pattern_len > carried && memcmp(window + i, pattern, pattern_len) == 0) {
      ++matches;
    }
  }
  return matches;
}

static void stream_read_task(void* arg) {
  auto* client = static_cast<stream_client_t*>(arg);
  const size_t carry = sizeof(STREAM_PART_START) - 2;
  char window[carry + 1024];
  size_t carried = 0;
  while (!client->stop) {
    int received = recv(client->fd, window + carried, sizeof(window) - carried, 0);
    if (received == 0 || (received < 0 && errno != EAGAIN && errno != EWOULDBLOCK)) {
      break;
    }
    if (received < 0) {
      continue;
    }
    size_t len = carried + received;
    client->parts += count_new_matches(window, carried, len, STREAM_PART_START);
    carried = len < carry ? len : carry;
    memmove(window, window + len - carried, carried);
  }
  xSemaphoreGive(client->reader_done);
  vTaskDelete(NULL);
}

stream_client_t* stream_open(uint16_t port) {
  auto* client = new stream_client_t{};
  client->reader_done = xSemaphoreCreateBinary();
  client->fd = http_connect(port);
  if (client->fd < 0) {
    return client;
  }
  char head[512] = {};
  client->status = http_get(client->fd, STREAM_PATH, head, sizeof(head));
  copy_header(head, "Content-Type: ", client->content_type, sizeof(client->content_type));
  if (client->status == 200) {
    xTaskCreate(stream_read_task, "stream_read", 4096, client, 5, nullptr);
  }
  return client;
}

void stream_close(stream_client_t* client) {
  client->stop = true;
  if (client->status == 200) {
    shutdown(client->fd, SHUT_RDWR);
    xSemaphoreTake(client->reader_done, portMAX_DELAY);
  }
  if (client->fd >= 0) {
    close(client->fd);
  }
  vSemaphoreDelete(client->reader_done);
  delete client;
}

stream_client_t* stream_open_or_fail() {
  stream_client_t* client = stream_open();
  if (client->status != 200) {
    TEST_FAIL_MESSAGE("the stream was not served");
  }
  return client;
}

bool wait_for_count(const std::atomic<int>& counter, int count, int timeout_ms) {
  const int poll_interval_ms = 10;
  TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(timeout_ms);
  while (counter < count) {
    if (xTaskGetTickCount() > deadline) {
      return false;
    }
    vTaskDelay(pdMS_TO_TICKS(poll_interval_ms));
  }
  return true;
}
