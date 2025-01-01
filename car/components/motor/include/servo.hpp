#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include "stdint.h"
#include "freertos/FreeRTOS.h"

void servo_init();

void move_pan(int8_t angle);
void move_tilt(int8_t angle);

#ifdef __cplusplus
}
#endif
