// http://<IP>/?command=3&value=127

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_check.h"
#include "esp_log.h"
#include "driver/gpio.h"
#include "driver/mcpwm.h"
#include "soc/mcpwm_struct.h" 
#include "soc/mcpwm_reg.h"
#include "camera.h"
#include "web_server.h"

static const char* TAG = "car";

#define COMMAND_ADVANCE 1
#define COMMAND_RETREAT 2
#define COMMAND_BRAKE 3
#define COMMAND_TURN_LEFT 4
#define COMMAND_TURN_RIGHT 5

static char g_command = 0;
static int g_value = 0;

void command_handler(char command, int *value) {
  if (command >= 1 && command <= 5) {
    g_command = command;
  } else {
    ESP_LOGW(TAG, "Unknown command: %d", command);
  }

  if (value != NULL) {
    g_value = *value;
  }
}

camera_fb_t* camera_frame = NULL;
frame_t* server_frame = NULL;

frame_t* frame_get_handler() {
  camera_frame = camera_fb_get();
  server_frame = (frame_t*)malloc(sizeof(frame_t));
  server_frame->buf = camera_frame->buf;
  server_frame->len = camera_frame->len;
  return server_frame;
}

void frame_return_handler(frame_t *frame) {
  camera_fb_return(camera_frame);
  camera_frame = NULL;

  free(server_frame);
  server_frame = NULL;
}

#define MOTOR_SPEED 60

typedef struct {
  int gpio_in1;
  int gpio_in2;
  mcpwm_unit_t pwm_unit;
  mcpwm_timer_t pwm_timer;
  mcpwm_io_signals_t pwm_io_signal_in1;
  mcpwm_io_signals_t pwm_io_signal_in2;
} motor_pins_t;

// Front left
motor_pins_t m1 = {
  .gpio_in1 = 12,
  .gpio_in2 = 13,
  .pwm_unit = MCPWM_UNIT_0,
  .pwm_timer = MCPWM_TIMER_0,
  .pwm_io_signal_in1 = MCPWM0A,
  .pwm_io_signal_in2 = MCPWM0B,
};

// Front right
motor_pins_t m2 = {
  .gpio_in1 = 14,
  .gpio_in2 = 21,
  .pwm_unit = MCPWM_UNIT_0,
  .pwm_timer = MCPWM_TIMER_1,
  .pwm_io_signal_in1 = MCPWM1A,
  .pwm_io_signal_in2 = MCPWM1B,
};

// Rear left
motor_pins_t m3 = {
  .gpio_in1 = 9,
  .gpio_in2 = 10,
  .pwm_unit = MCPWM_UNIT_1,
  .pwm_timer = MCPWM_TIMER_0,
  .pwm_io_signal_in1 = MCPWM0A,
  .pwm_io_signal_in2 = MCPWM0B,
};

// Rear right
motor_pins_t m4 = {
  .gpio_in1 = 47,
  .gpio_in2 = 11,
  .pwm_unit = MCPWM_UNIT_1,
  .pwm_timer = MCPWM_TIMER_1,
  .pwm_io_signal_in1 = MCPWM1A,
  .pwm_io_signal_in2 = MCPWM1B,
};

motor_pins_t motors[4] = {m1, m2, m3, m4};

void motor_setup() {
  mcpwm_config_t pwm_config;
  pwm_config.frequency = 1000;
  pwm_config.cmpr_a = 0;
  pwm_config.cmpr_b = 0;
  pwm_config.counter_mode = MCPWM_UP_COUNTER;
  pwm_config.duty_mode = MCPWM_DUTY_MODE_0;

  for (int i=0; i < 4; i++) {
    motor_pins_t &m = motors[i];
    mcpwm_gpio_init(m.pwm_unit,m.pwm_io_signal_in1,m.gpio_in1);
    mcpwm_gpio_init(m.pwm_unit,m.pwm_io_signal_in2,m.gpio_in2);
    mcpwm_init(m.pwm_unit,m.pwm_timer,&pwm_config);
  }
}

void motor_advance(motor_pins_t &motor, uint8_t speed)
{
  mcpwm_set_duty_type(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_A,MCPWM_DUTY_MODE_0);
  mcpwm_set_signal_low(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_B);
  mcpwm_set_duty(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_A,speed);
}

void motor_retreat(motor_pins_t &motor, uint8_t speed)
{
  mcpwm_set_duty_type(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_A,MCPWM_DUTY_MODE_0);
  mcpwm_set_signal_high(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_B);
  mcpwm_set_duty(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_A,speed);
}

void motor_brake(motor_pins_t &motor)
{
  mcpwm_set_signal_high(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_A);
  mcpwm_set_signal_high(motor.pwm_unit,motor.pwm_timer,MCPWM_GEN_B);
}

void car_advance(uint8_t speed)
{
  for (int i=0; i < 4; i++) {
    motor_pins_t &m = motors[i];
    motor_advance(m, speed);
  }
}

void car_retreat(uint8_t speed)
{
  for (int i=0; i < 4; i++) {
    motor_pins_t &m = motors[i];
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
    motor_pins_t &m = motors[i];
    motor_brake(m);
  }
}

void setup()
{
  camera_setup();
  motor_setup();
  wifi_setup();
  register_command_handler(command_handler);
  register_frame_get_handler(frame_get_handler);
  register_frame_return_handler(frame_return_handler);
}

void loop()
{
  if (g_command != 0) {
    switch (g_command) {
      case COMMAND_ADVANCE:
        ESP_LOGI(TAG, "COMMAND_ADVANCE");
        car_advance(MOTOR_SPEED);
        break;
      case COMMAND_RETREAT:
        ESP_LOGI(TAG, "COMMAND_RETREAT");
        car_retreat(MOTOR_SPEED);
        break;
      case COMMAND_BRAKE:
        ESP_LOGI(TAG, "COMMAND_BRAKE");
        car_brake();
        break;
      case COMMAND_TURN_LEFT:
        ESP_LOGI(TAG, "COMMAND_TURN_LEFT");
        car_turn_left(MOTOR_SPEED);
        break;
      case COMMAND_TURN_RIGHT:
        ESP_LOGI(TAG, "COMMAND_TURN_RIGHT");
        car_turn_right(MOTOR_SPEED);
        break;
      default:
        ESP_LOGI(TAG, "Unknown command");
    }
    g_command = 0;
    g_value = 0;
  }

  vTaskDelay(10/portTICK_PERIOD_MS);
}

extern "C" void app_main()
{
  setup();
  while(true){
    loop();
  }
}
