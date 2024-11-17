#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include "esp_http_server.h"

void wifi_setup();

void register_command_handler(void (*handler)(char, int*));

typedef struct {
    unsigned char* buf;
    size_t len;
} frame_t;

void register_frame_get_handler(frame_t* (*handler)());
void register_frame_return_handler(void (*handler)(frame_t*));

#ifdef __cplusplus
}
#endif
