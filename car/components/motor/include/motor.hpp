#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include "stdint.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

void motor_setup(QueueHandle_t command_queue);

void car_advance(uint8_t speed);
void car_retreat(uint8_t speed);
void car_brake();
void car_turn_left(uint8_t speed);
void car_turn_right(uint8_t speed);

#define COMMAND_ADVANCE 1
#define COMMAND_RETREAT 2
#define COMMAND_BRAKE 3
#define COMMAND_TURN_LEFT 4
#define COMMAND_TURN_RIGHT 5

typedef struct command_packet {
  char command;
  int value;
} command_packet_t;

void command_task(void *p);

#ifdef __cplusplus
}
#endif
