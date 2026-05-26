#include "servo.hpp"
#include "utils.hpp"
#include "esp_log.h"
#include "driver/mcpwm_prelude.h"

#define MIN_ANGLE -90  // RIGHT/UP
#define MAX_ANGLE 90   // LEFT/DOWN
#define MIN_DUTY 500
#define MAX_DUTY 2400

#define SERVO_PWM_RESOLUTION_HZ 1000000
#define SERVO_PWM_FREQ_HZ       50
#define SERVO_PWM_PERIOD_TICKS  (SERVO_PWM_RESOLUTION_HZ / SERVO_PWM_FREQ_HZ)

typedef struct {
  int gpio_in;
  int group_id;
  mcpwm_timer_handle_t timer;
  mcpwm_oper_handle_t oper;
  mcpwm_cmpr_handle_t cmpr;
  mcpwm_gen_handle_t gen;
} servo_t;

static servo_t pan_servo  = {3,  0, nullptr, nullptr, nullptr, nullptr};
static servo_t tilt_servo = {38, 1, nullptr, nullptr, nullptr, nullptr};

static int map_angle_to_duty(int angle) {
  return interpolate(angle, MIN_ANGLE, MAX_ANGLE, MIN_DUTY, MAX_DUTY);
}

static void servo_mcpwm_init(servo_t* s) {
  mcpwm_timer_config_t timer_cfg = {};
  timer_cfg.group_id = s->group_id;
  timer_cfg.clk_src = MCPWM_TIMER_CLK_SRC_DEFAULT;
  timer_cfg.resolution_hz = SERVO_PWM_RESOLUTION_HZ;
  timer_cfg.count_mode = MCPWM_TIMER_COUNT_MODE_UP;
  timer_cfg.period_ticks = SERVO_PWM_PERIOD_TICKS;
  ESP_ERROR_CHECK(mcpwm_new_timer(&timer_cfg, &s->timer));

  mcpwm_operator_config_t oper_cfg = {};
  oper_cfg.group_id = s->group_id;
  ESP_ERROR_CHECK(mcpwm_new_operator(&oper_cfg, &s->oper));
  ESP_ERROR_CHECK(mcpwm_operator_connect_timer(s->oper, s->timer));

  mcpwm_comparator_config_t cmpr_cfg = {};
  cmpr_cfg.flags.update_cmp_on_tez = true;
  ESP_ERROR_CHECK(mcpwm_new_comparator(s->oper, &cmpr_cfg, &s->cmpr));
  ESP_ERROR_CHECK(mcpwm_comparator_set_compare_value(s->cmpr, 0));

  mcpwm_generator_config_t gen_cfg = {};
  gen_cfg.gen_gpio_num = s->gpio_in;
  ESP_ERROR_CHECK(mcpwm_new_generator(s->oper, &gen_cfg, &s->gen));

  // High on timer empty, low on comparator match — standard servo PWM
  ESP_ERROR_CHECK(mcpwm_generator_set_action_on_timer_event(s->gen,
      MCPWM_GEN_TIMER_EVENT_ACTION(MCPWM_TIMER_DIRECTION_UP, MCPWM_TIMER_EVENT_EMPTY, MCPWM_GEN_ACTION_HIGH)));
  ESP_ERROR_CHECK(mcpwm_generator_set_action_on_compare_event(s->gen,
      MCPWM_GEN_COMPARE_EVENT_ACTION(MCPWM_TIMER_DIRECTION_UP, s->cmpr, MCPWM_GEN_ACTION_LOW)));

  ESP_ERROR_CHECK(mcpwm_timer_enable(s->timer));
  ESP_ERROR_CHECK(mcpwm_timer_start_stop(s->timer, MCPWM_TIMER_START_NO_STOP));
}

void servo_init() {
  servo_mcpwm_init(&pan_servo);
  servo_mcpwm_init(&tilt_servo);

  move_pan(0);
  move_tilt(0);
}

static void move_servo(servo_t* servo, int angle) {
  uint32_t duty_us = (uint32_t)map_angle_to_duty(angle);
  ESP_ERROR_CHECK(mcpwm_comparator_set_compare_value(servo->cmpr, duty_us));
  // Should we wait for servo to rotate?
  // uint32_t full_rotation_duration_ms = 150 * (180/60);
  // vTaskDelay(full_rotation_duration_ms/portTICK_PERIOD_MS);
}

void move_pan(int8_t angle) {
  int servo_angle = -angle;  // Convert angle (-90=LEFT) to servo angle (90=LEFT)
  move_servo(&pan_servo, servo_angle);
}

void move_tilt(int8_t angle) {
  int servo_angle = -angle;  // Convert angle (-90=DOWN) to servo angle (90=LEFT)
  move_servo(&tilt_servo, servo_angle);
}
