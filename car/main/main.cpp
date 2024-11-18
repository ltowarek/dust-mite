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

#define COMMAND_START 1
#define COMMAND_END 2
#define COMMAND_TURN 3
#define COMMAND_BRAKE 4
#define COMMAND_ACCELERATE 5

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

#define M1_IN1 12
#define M1_IN2 13
#define M2_IN1 14
#define M2_IN2 21
#define M3_IN1 9
#define M3_IN2 10
#define M4_IN1 47
#define M4_IN2 11

void motor_setup() {
  mcpwm_config_t pwm_config;
  pwm_config.frequency = 1000;
  pwm_config.cmpr_a = 0;
  pwm_config.cmpr_b = 0;
  pwm_config.counter_mode = MCPWM_UP_COUNTER;
  pwm_config.duty_mode = MCPWM_DUTY_MODE_0;

  mcpwm_gpio_init(MCPWM_UNIT_0,MCPWM0A,M1_IN1);
  mcpwm_gpio_init(MCPWM_UNIT_0,MCPWM0B,M1_IN2);
  mcpwm_init(MCPWM_UNIT_0,MCPWM_TIMER_0,&pwm_config);

  mcpwm_gpio_init(MCPWM_UNIT_0,MCPWM1A,M2_IN1);
  mcpwm_gpio_init(MCPWM_UNIT_0,MCPWM1B,M2_IN2);
  mcpwm_init(MCPWM_UNIT_0,MCPWM_TIMER_1,&pwm_config);

  mcpwm_gpio_init(MCPWM_UNIT_1,MCPWM0A,M3_IN1);
  mcpwm_gpio_init(MCPWM_UNIT_1,MCPWM0B,M3_IN2);
  mcpwm_init(MCPWM_UNIT_1,MCPWM_TIMER_0,&pwm_config);

  mcpwm_gpio_init(MCPWM_UNIT_1,MCPWM1A,M4_IN1);
  mcpwm_gpio_init(MCPWM_UNIT_1,MCPWM1B,M4_IN2);
  mcpwm_init(MCPWM_UNIT_1,MCPWM_TIMER_1,&pwm_config);
}


void accelerate(uint8_t speed)
{
  mcpwm_set_duty_type(MCPWM_UNIT_0,MCPWM_TIMER_0,MCPWM_GEN_A,MCPWM_DUTY_MODE_0);
  mcpwm_set_signal_low(MCPWM_UNIT_0,MCPWM_TIMER_0,MCPWM_GEN_B);
  mcpwm_set_duty(MCPWM_UNIT_0,MCPWM_TIMER_0,MCPWM_GEN_A,speed);

  mcpwm_set_duty_type(MCPWM_UNIT_0,MCPWM_TIMER_1,MCPWM_GEN_A,MCPWM_DUTY_MODE_0);
  mcpwm_set_signal_low(MCPWM_UNIT_0,MCPWM_TIMER_1,MCPWM_GEN_B);
  mcpwm_set_duty(MCPWM_UNIT_0,MCPWM_TIMER_1,MCPWM_GEN_A,speed);

  mcpwm_set_duty_type(MCPWM_UNIT_1,MCPWM_TIMER_0,MCPWM_GEN_A,MCPWM_DUTY_MODE_0);
  mcpwm_set_signal_low(MCPWM_UNIT_1,MCPWM_TIMER_0,MCPWM_GEN_B);
  mcpwm_set_duty(MCPWM_UNIT_1,MCPWM_TIMER_0,MCPWM_GEN_A,speed);

  mcpwm_set_duty_type(MCPWM_UNIT_1,MCPWM_TIMER_1,MCPWM_GEN_A,MCPWM_DUTY_MODE_0);
  mcpwm_set_signal_low(MCPWM_UNIT_1,MCPWM_TIMER_1,MCPWM_GEN_B);
  mcpwm_set_duty(MCPWM_UNIT_1,MCPWM_TIMER_1,MCPWM_GEN_A,speed);
}

void brake()
{
  mcpwm_set_signal_high(MCPWM_UNIT_0,MCPWM_TIMER_0,MCPWM_GEN_A);
  mcpwm_set_signal_high(MCPWM_UNIT_0,MCPWM_TIMER_0,MCPWM_GEN_B);

  mcpwm_set_signal_high(MCPWM_UNIT_0,MCPWM_TIMER_1,MCPWM_GEN_A);
  mcpwm_set_signal_high(MCPWM_UNIT_0,MCPWM_TIMER_1,MCPWM_GEN_B);

  mcpwm_set_signal_high(MCPWM_UNIT_1,MCPWM_TIMER_0,MCPWM_GEN_A);
  mcpwm_set_signal_high(MCPWM_UNIT_1,MCPWM_TIMER_0,MCPWM_GEN_B);

  mcpwm_set_signal_high(MCPWM_UNIT_1,MCPWM_TIMER_1,MCPWM_GEN_A);
  mcpwm_set_signal_high(MCPWM_UNIT_1,MCPWM_TIMER_1,MCPWM_GEN_B);
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
      case COMMAND_START:
        ESP_LOGI(TAG, "COMMAND_START");
        break;
      case COMMAND_END:
        ESP_LOGI(TAG, "COMMAND_END");
        break;
      case COMMAND_TURN:
        ESP_LOGI(TAG, "COMMAND_TURN: %d", g_value);
        break;
      case COMMAND_BRAKE:
        ESP_LOGI(TAG, "COMMAND_BRAKE: %d", g_value);
        brake();
        break;
      case COMMAND_ACCELERATE:
        ESP_LOGI(TAG, "COMMAND_ACCELERATE: %d", g_value);
        // TODO: map value to proper range after motor/pwm calibration
        accelerate(60);
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
