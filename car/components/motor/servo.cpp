#include "servo.hpp"
#include "utils.hpp"
#include "esp_log.h"
#include "driver/mcpwm.h"

static const char* TAG = "servo";

#define MIN_ANGLE -90  // RIGHT/UP
#define MAX_ANGLE 90  // LEFT/DOWN
#define MIN_DUTY 500
#define MAX_DUTY 2400

typedef struct {
  int gpio_in;
  mcpwm_unit_t pwm_unit;
  mcpwm_timer_t pwm_timer;
  mcpwm_io_signals_t pwm_io_signal_in;
} servo_pins_t;

const servo_pins_t pan_servo = {
  .gpio_in = 3,
  .pwm_unit = MCPWM_UNIT_0,
  .pwm_timer = MCPWM_TIMER_0,
  .pwm_io_signal_in = MCPWM0A,
};

const servo_pins_t tilt_servo = {
  .gpio_in = 38,
  .pwm_unit = MCPWM_UNIT_0,
  .pwm_timer = MCPWM_TIMER_1,
  .pwm_io_signal_in = MCPWM1A,
};

int map_angle_to_duty(int angle) {
  return interpolate(angle, MIN_ANGLE, MAX_ANGLE, MIN_DUTY, MAX_DUTY);
}

void servo_init() {
  mcpwm_config_t pwm_config = {};
  pwm_config.frequency = 50;
  pwm_config.cmpr_a = 0;
  pwm_config.counter_mode = MCPWM_UP_COUNTER;
  pwm_config.duty_mode = MCPWM_DUTY_MODE_0;

  ESP_ERROR_CHECK(mcpwm_gpio_init(pan_servo.pwm_unit, pan_servo.pwm_io_signal_in, pan_servo.gpio_in));
  ESP_ERROR_CHECK(mcpwm_init(pan_servo.pwm_unit, pan_servo.pwm_timer, &pwm_config));

  ESP_ERROR_CHECK(mcpwm_gpio_init(tilt_servo.pwm_unit, tilt_servo.pwm_io_signal_in, tilt_servo.gpio_in));
  ESP_ERROR_CHECK(mcpwm_init(tilt_servo.pwm_unit, tilt_servo.pwm_timer, &pwm_config));

  move_pan(0);
  move_tilt(0);
}

void move_servo(servo_pins_t servo, int angle) {
  uint32_t duty = map_angle_to_duty(angle);
  ESP_ERROR_CHECK(mcpwm_set_duty_in_us(servo.pwm_unit, servo.pwm_timer, MCPWM_OPR_A, duty));
  // Should we wait for servo to rotate?
  // uint32_t full_rotation_duration_ms = 150 * (180/60);
  // vTaskDelay(full_rotation_duration_ms/portTICK_PERIOD_MS);
}

void move_pan(int8_t angle) {
  int servo_angle = -angle;  // Convert angle (-90=LEFT) to servo angle (90=LEFT)
  move_servo(pan_servo, servo_angle);
}

void move_tilt(int8_t angle) {
  int servo_angle = -angle;  // Convert angle (-90=DOWN) to servo angle (90=LEFT)
  move_servo(tilt_servo, servo_angle);
}
