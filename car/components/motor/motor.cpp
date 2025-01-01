#include "motor.hpp"
#include "servo.hpp"
#include "utils.hpp"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "driver/gpio.h"
#include "driver/mcpwm.h"
#include "soc/mcpwm_struct.h" 
#include "soc/mcpwm_reg.h"

static const char* TAG = "motor";

#define MOTOR_DEAD_ZONE 40

typedef struct {
  int gpio_in1;
  int gpio_in2;
  mcpwm_unit_t pwm_unit;
  mcpwm_timer_t pwm_timer;
  mcpwm_io_signals_t pwm_io_signal_in1;
  mcpwm_io_signals_t pwm_io_signal_in2;
} motor_pins_t;

// Front left
const motor_pins_t m1 = {
  .gpio_in1 = 12,
  .gpio_in2 = 13,
  .pwm_unit = MCPWM_UNIT_0,
  .pwm_timer = MCPWM_TIMER_0,
  .pwm_io_signal_in1 = MCPWM0A,
  .pwm_io_signal_in2 = MCPWM0B,
};

// Front right
const motor_pins_t m2 = {
  .gpio_in1 = 14,
  .gpio_in2 = 21,
  .pwm_unit = MCPWM_UNIT_0,
  .pwm_timer = MCPWM_TIMER_1,
  .pwm_io_signal_in1 = MCPWM1A,
  .pwm_io_signal_in2 = MCPWM1B,
};

// Rear left
const motor_pins_t m3 = {
  .gpio_in1 = 9,
  .gpio_in2 = 10,
  .pwm_unit = MCPWM_UNIT_1,
  .pwm_timer = MCPWM_TIMER_0,
  .pwm_io_signal_in1 = MCPWM0A,
  .pwm_io_signal_in2 = MCPWM0B,
};

// Rear right
const motor_pins_t m4 = {
  .gpio_in1 = 47,
  .gpio_in2 = 11,
  .pwm_unit = MCPWM_UNIT_1,
  .pwm_timer = MCPWM_TIMER_1,
  .pwm_io_signal_in1 = MCPWM1A,
  .pwm_io_signal_in2 = MCPWM1B,
};

const motor_pins_t motors[4] = {m1, m2, m3, m4};

static QueueHandle_t g_command_queue = NULL;
static TaskHandle_t g_command_task_handle = NULL;

void command_task(void *p) {
  command_packet_t packet = {0, 0};
  while (true) {
    if (xQueueReceive(g_command_queue, &packet, portMAX_DELAY) != pdPASS) {
      ESP_LOGE(TAG, "xQueueReceive failed");
      return;
    }
    if (packet.command != 0) {
      switch (packet.command) {
        case COMMAND_ADVANCE:
          ESP_LOGI(TAG, "COMMAND_ADVANCE: %d", packet.value);
          car_advance(packet.value);
          break;
        case COMMAND_RETREAT:
          ESP_LOGI(TAG, "COMMAND_RETREAT");
          car_retreat(packet.value);
          break;
        case COMMAND_BRAKE:
          ESP_LOGI(TAG, "COMMAND_BRAKE");
          car_brake();
          break;
        case COMMAND_TURN_LEFT:
          ESP_LOGI(TAG, "COMMAND_TURN_LEFT: %d", packet.value);
          car_turn_left(packet.value);
          break;
        case COMMAND_TURN_RIGHT:
          ESP_LOGI(TAG, "COMMAND_TURN_RIGHT: %d", packet.value);
          car_turn_right(packet.value);
          break;
        // TODO: Split car and camera commands
        // Currently there is no way to drive a car and look around
        // What's more, you can't look horizontally and vertically and the same time
        case COMMAND_LOOK_HORIZONTALLY:
          ESP_LOGI(TAG, "COMMAND_LOOK_HORIZONTALLY: %d", packet.value);
          move_pan(packet.value);
          break;
        case COMMAND_LOOK_VERTICALLY:
          ESP_LOGI(TAG, "COMMAND_LOOK_VERTICALLY: %d", packet.value);
          move_tilt(packet.value);
          break;
        default:
          ESP_LOGI(TAG, "Unknown command: %d", packet.command);
      }
      packet = {0, 0};
    }
  }
}

void motor_init() {
  mcpwm_config_t pwm_config;
  pwm_config.frequency = 1000;
  pwm_config.cmpr_a = 0;
  pwm_config.cmpr_b = 0;
  pwm_config.counter_mode = MCPWM_UP_COUNTER;
  pwm_config.duty_mode = MCPWM_DUTY_MODE_0;

  for (int i=0; i < 4; i++) {
    const motor_pins_t &m = motors[i];
    mcpwm_gpio_init(m.pwm_unit,m.pwm_io_signal_in1,m.gpio_in1);
    mcpwm_gpio_init(m.pwm_unit,m.pwm_io_signal_in2,m.gpio_in2);
    mcpwm_init(m.pwm_unit,m.pwm_timer,&pwm_config);
  }
}

void motor_setup(QueueHandle_t command_queue) {
  motor_init();
  // Not enough GPIOs to run motors + servos + telemetry
  // servo_init();

  g_command_queue = command_queue;
  if (xTaskCreate(command_task, "command_task", 4096, (void *)0, 1, &g_command_task_handle) != pdPASS) {
    ESP_LOGE(TAG, "xTaskCreate(command_task) failed");
    return;
  }
}

void motor_advance(const motor_pins_t &motor, uint8_t speed)
{
  speed = (uint8_t)interpolate(speed, 0, 100, MOTOR_DEAD_ZONE, 100);
  mcpwm_set_duty_type(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_A,MCPWM_DUTY_MODE_0);
  mcpwm_set_signal_low(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_B);
  mcpwm_set_duty(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_A,speed);
}

void motor_retreat(const motor_pins_t &motor, uint8_t speed)
{
  speed = (uint8_t)interpolate(speed, 0, 100, MOTOR_DEAD_ZONE, 100);
  mcpwm_set_duty_type(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_B,MCPWM_DUTY_MODE_0);
  mcpwm_set_signal_low(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_A);
  mcpwm_set_duty(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_B,speed);
}

void motor_brake(const motor_pins_t &motor)
{
  mcpwm_set_signal_high(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_A);
  mcpwm_set_signal_high(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_B);
}

void car_advance(uint8_t speed)
{
  for (int i=0; i < 4; i++) {
    const motor_pins_t &m = motors[i];
    motor_advance(m, speed);
  }
}

void car_retreat(uint8_t speed)
{
  for (int i=0; i < 4; i++) {
    const motor_pins_t &m = motors[i];
    motor_retreat(m, speed);
  }
}

void car_turn_left(uint8_t speed)
{
  motor_advance(m2, speed);
  motor_advance(m4, speed);
  motor_retreat(m1, speed);
  motor_retreat(m3, speed);
}

void car_turn_right(uint8_t speed)
{
  motor_advance(m1, speed);
  motor_advance(m3, speed);
  motor_retreat(m2, speed);
  motor_retreat(m4, speed);
}

void car_brake()
{
  for (int i=0; i < 4; i++) {
    const motor_pins_t &m = motors[i];
    motor_brake(m);
  }
}
