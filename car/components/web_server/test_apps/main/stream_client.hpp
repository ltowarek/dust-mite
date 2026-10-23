#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "web_server.hpp"

inline constexpr int OPEN_TIMEOUT_MS = 8000;
inline constexpr int FIRST_FRAME_BUDGET_MS = 2000;
inline constexpr char STREAM_PATH[] = "/stream";

// A Camera stream client over a plain socket, so a test can count parts and leave abruptly.
struct stream_client_t {
  int fd = -1;
  int status = 0;
  char content_type[64] = {};
  std::atomic<int> parts{0};
  std::atomic<bool> stop{false};
  SemaphoreHandle_t reader_done = nullptr;
};

int http_connect(uint16_t port);
// Sends a GET and reads the response head; returns its status, or 0 when none arrived.
int http_get(int fd, const char* path, char* head, size_t head_size);
// Leaves the client unread when the response is not a stream.
stream_client_t* stream_open(uint16_t port = WEB_SERVER_CAMERA_PORT);
// Drops the connection without waiting for the server, as a departing viewer does.
void stream_close(stream_client_t* client);
stream_client_t* stream_open_or_fail();
bool wait_for_count(const std::atomic<int>& counter, int count, int timeout_ms);
