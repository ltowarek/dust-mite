#include "motor.hpp"
#include "servo.hpp"
#include "utils.hpp"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "driver/gpio.h"
#include "driver/mcpwm_prelude.h"

static const char* TAG = "motor";

#define MOTOR_DEAD_ZONE 40
#define MOTOR_PWM_RESOLUTION_HZ 1000000
#define MOTOR_PWM_FREQ_HZ 1000
#define MOTOR_PWM_PERIOD_TICKS (MOTOR_PWM_RESOLUTION_HZ / MOTOR_PWM_FREQ_HZ)

typedef struct {
  int gpio_in1;
  int gpio_in2;
  int group_id;
  mcpwm_timer_handle_t timer;
  mcpwm_oper_handle_t oper;
  mcpwm_cmpr_handle_t cmpr_a;
  mcpwm_cmpr_handle_t cmpr_b;
  mcpwm_gen_handle_t gen_a;
  mcpwm_gen_handle_t gen_b;
} motor_t;

// Front left
static motor_t m1 = {12, 13, 0, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr};
// Front right
static motor_t m2 = {14, 21, 0, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr};
// Rear left
static motor_t m3 = {9, 10, 1, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr};
// Rear right
static motor_t m4 = {47, 11, 1, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr};

static motor_t* motors[4] = {&m1, &m2, &m3, &m4};

static QueueHandle_t g_command_queue = NULL;
static TaskHandle_t g_command_task_handle = NULL;

void command_task(void* p) {
  command_packet_t packet = {0, 0};
  while (true) {
    if (xQueueReceive(g_command_queue, &packet, portMAX_DELAY) != pdPASS) {
      // cppcheck-suppress syntaxError ; cppcheck's parser can't resolve ESP-IDF's variadic ESP_LOGx macros
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

static void motor_mcpwm_init(motor_t* m) {
  mcpwm_timer_config_t timer_cfg = {};
  timer_cfg.group_id = m->group_id;
  timer_cfg.clk_src = MCPWM_TIMER_CLK_SRC_DEFAULT;
  timer_cfg.resolution_hz = MOTOR_PWM_RESOLUTION_HZ;
  timer_cfg.count_mode = MCPWM_TIMER_COUNT_MODE_UP;
  timer_cfg.period_ticks = MOTOR_PWM_PERIOD_TICKS;
  ESP_ERROR_CHECK(mcpwm_new_timer(&timer_cfg, &m->timer));

  mcpwm_operator_config_t oper_cfg = {};
  oper_cfg.group_id = m->group_id;
  ESP_ERROR_CHECK(mcpwm_new_operator(&oper_cfg, &m->oper));
  ESP_ERROR_CHECK(mcpwm_operator_connect_timer(m->oper, m->timer));

  mcpwm_comparator_config_t cmpr_cfg = {};
  cmpr_cfg.flags.update_cmp_on_tez = true;
  ESP_ERROR_CHECK(mcpwm_new_comparator(m->oper, &cmpr_cfg, &m->cmpr_a));
  ESP_ERROR_CHECK(mcpwm_new_comparator(m->oper, &cmpr_cfg, &m->cmpr_b));
  ESP_ERROR_CHECK(mcpwm_comparator_set_compare_value(m->cmpr_a, 0));
  ESP_ERROR_CHECK(mcpwm_comparator_set_compare_value(m->cmpr_b, 0));

  mcpwm_generator_config_t gen_cfg = {};
  gen_cfg.gen_gpio_num = m->gpio_in1;
  ESP_ERROR_CHECK(mcpwm_new_generator(m->oper, &gen_cfg, &m->gen_a));
  gen_cfg.gen_gpio_num = m->gpio_in2;
  ESP_ERROR_CHECK(mcpwm_new_generator(m->oper, &gen_cfg, &m->gen_b));

  ESP_ERROR_CHECK(mcpwm_generator_set_action_on_timer_event(
      m->gen_a, MCPWM_GEN_TIMER_EVENT_ACTION(MCPWM_TIMER_DIRECTION_UP, MCPWM_TIMER_EVENT_EMPTY,
                                             MCPWM_GEN_ACTION_HIGH)));
  ESP_ERROR_CHECK(mcpwm_generator_set_action_on_compare_event(
      m->gen_a,
      MCPWM_GEN_COMPARE_EVENT_ACTION(MCPWM_TIMER_DIRECTION_UP, m->cmpr_a, MCPWM_GEN_ACTION_LOW)));

  ESP_ERROR_CHECK(mcpwm_generator_set_action_on_timer_event(
      m->gen_b, MCPWM_GEN_TIMER_EVENT_ACTION(MCPWM_TIMER_DIRECTION_UP, MCPWM_TIMER_EVENT_EMPTY,
                                             MCPWM_GEN_ACTION_HIGH)));
  ESP_ERROR_CHECK(mcpwm_generator_set_action_on_compare_event(
      m->gen_b,
      MCPWM_GEN_COMPARE_EVENT_ACTION(MCPWM_TIMER_DIRECTION_UP, m->cmpr_b, MCPWM_GEN_ACTION_LOW)));

  // Start with both outputs forced low
  ESP_ERROR_CHECK(mcpwm_generator_set_force_level(m->gen_a, 0, true));
  ESP_ERROR_CHECK(mcpwm_generator_set_force_level(m->gen_b, 0, true));

  ESP_ERROR_CHECK(mcpwm_timer_enable(m->timer));
  ESP_ERROR_CHECK(mcpwm_timer_start_stop(m->timer, MCPWM_TIMER_START_NO_STOP));
}

void motor_init() {
  for (int i = 0; i < 4; i++) {
    motor_mcpwm_init(motors[i]);
  }
}

void motor_setup(QueueHandle_t command_queue) {
  motor_init();
  servo_init();

  g_command_queue = command_queue;
  if (xTaskCreate(command_task, "command_task", 4096, (void*)0, 1, &g_command_task_handle) !=
      pdPASS) {
    ESP_LOGE(TAG, "xTaskCreate(command_task) failed");
    return;
  }
}

static void motor_advance(motor_t* motor, uint8_t speed) {
  speed = (uint8_t)interpolate(speed, 0, 100, MOTOR_DEAD_ZONE, 100);
  uint32_t cmp = (uint32_t)speed * MOTOR_PWM_PERIOD_TICKS / 100;
  ESP_ERROR_CHECK(mcpwm_comparator_set_compare_value(motor->cmpr_a, cmp));
  ESP_ERROR_CHECK(mcpwm_generator_set_force_level(motor->gen_b, 0, true));
  ESP_ERROR_CHECK(mcpwm_generator_set_force_level(motor->gen_a, -1, false));
}

static void motor_retreat(motor_t* motor, uint8_t speed) {
  speed = (uint8_t)interpolate(speed, 0, 100, MOTOR_DEAD_ZONE, 100);
  uint32_t cmp = (uint32_t)speed * MOTOR_PWM_PERIOD_TICKS / 100;
  ESP_ERROR_CHECK(mcpwm_comparator_set_compare_value(motor->cmpr_b, cmp));
  ESP_ERROR_CHECK(mcpwm_generator_set_force_level(motor->gen_a, 0, true));
  ESP_ERROR_CHECK(mcpwm_generator_set_force_level(motor->gen_b, -1, false));
}

static void motor_brake(motor_t* motor) {
  ESP_ERROR_CHECK(mcpwm_generator_set_force_level(motor->gen_a, 1, true));
  ESP_ERROR_CHECK(mcpwm_generator_set_force_level(motor->gen_b, 1, true));
}

void car_advance(uint8_t speed) {
  for (int i = 0; i < 4; i++) {
    motor_advance(motors[i], speed);
  }
}

void car_retreat(uint8_t speed) {
  for (int i = 0; i < 4; i++) {
    motor_retreat(motors[i], speed);
  }
}

void car_turn_left(uint8_t speed) {
  motor_advance(&m2, speed);
  motor_advance(&m4, speed);
  motor_retreat(&m1, speed);
  motor_retreat(&m3, speed);
}

void car_turn_right(uint8_t speed) {
  motor_advance(&m1, speed);
  motor_advance(&m3, speed);
  motor_retreat(&m2, speed);
  motor_retreat(&m4, speed);
}

void car_brake() {
  for (int i = 0; i < 4; i++) {
    motor_brake(motors[i]);
  }
}
