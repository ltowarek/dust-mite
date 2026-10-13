#pragma once

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

// The queue the web server writes drive commands to. Nothing else reads it in the test app, so the
// test cases can check what the server wrote.
extern QueueHandle_t test_app_command_queue;
