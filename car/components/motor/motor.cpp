#include "motor.hpp"
#include "driver/gpio.h"
#include "driver/mcpwm.h"
#include "soc/mcpwm_struct.h" 
#include "soc/mcpwm_reg.h"

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

void motor_setup() {
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

void motor_advance(const motor_pins_t &motor, uint8_t speed)
{
  mcpwm_set_duty_type(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_A,MCPWM_DUTY_MODE_0);
  mcpwm_set_signal_low(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_B);
  mcpwm_set_duty(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_A,speed);
}

void motor_retreat(const motor_pins_t &motor, uint8_t speed)
{
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
