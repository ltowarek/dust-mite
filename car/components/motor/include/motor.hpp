#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include "stdint.h"

#define MOTOR_SPEED 60

void motor_setup();

void car_advance(uint8_t speed);
void car_retreat(uint8_t speed);
void car_brake();
void car_turn_left(uint8_t speed);
void car_turn_right(uint8_t speed);

#ifdef __cplusplus
}
#endif
