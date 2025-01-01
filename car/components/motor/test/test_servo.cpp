// // TODO: There is linker error due to duplicated setUp/tearDown functions as they are defined in multiple component tests (camera + telemetry)

// #include "stdio.h"
// #include "servo.hpp"
// #include "unity.h"
// #include "esp_log.h"

// int is_initialized = 0;

// void setUp(void)
// {
//     if (is_initialized == 0) {
//         servo_init();
//         is_initialized = 1;
//     }
// }

// void tearDown(void)
// {
// }

// TEST_CASE("pan", "[servo]")
// {
//     int angle = 0;
//     ESP_LOGI("test", "Angle: %d", angle);
//     move_pan(angle);
//     vTaskDelay(pdMS_TO_TICKS(1000));

//     angle = 90;
//     ESP_LOGI("test", "Angle: %d", angle);
//     move_pan(angle);
//     vTaskDelay(pdMS_TO_TICKS(1000));

//     angle = -90;
//     ESP_LOGI("test", "Angle: %d", angle);
//     move_pan(angle);
//     vTaskDelay(pdMS_TO_TICKS(1000));

//     angle = 0;
//     ESP_LOGI("test", "Angle: %d", angle);
//     move_pan(angle);
//     vTaskDelay(pdMS_TO_TICKS(1000));
// }

// TEST_CASE("tilt", "[servo]")
// {
//     int angle = 0;
//     ESP_LOGI("test", "Angle: %d", angle);
//     move_tilt(angle);
//     vTaskDelay(pdMS_TO_TICKS(1000));

//     angle = 90;
//     ESP_LOGI("test", "Angle: %d", angle);
//     move_tilt(angle);
//     vTaskDelay(pdMS_TO_TICKS(1000));

//     angle = -90;
//     ESP_LOGI("test", "Angle: %d", angle);
//     move_tilt(angle);
//     vTaskDelay(pdMS_TO_TICKS(1000));

//     angle = 0;
//     ESP_LOGI("test", "Angle: %d", angle);
//     move_tilt(angle);
//     vTaskDelay(pdMS_TO_TICKS(1000));
// }
