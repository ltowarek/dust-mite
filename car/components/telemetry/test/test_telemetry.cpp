// TODO: There is linker error due to duplicated setUp/tearDown functions as they are defined in multiple component tests (camera + telemetry)

// #include "stdio.h"
// #include "telemetry.hpp"
// #include "unity.h"
// #include "esp_log.h"

// int is_initialized = 0;

// void setUp(void)
// {
//     if (is_initialized == 0) {
//         telemetry_init();
//         is_initialized = 1;
//     }
// }

// void tearDown(void)
// {
// }

// TEST_CASE("speed", "[pcnt]")
// {
//     while (true) {
//         ESP_LOGI("test", "speed: %f [km/h]", get_speed());
//         vTaskDelay(pdMS_TO_TICKS(1000));
//     }
// }

// TEST_CASE("accelerometer", "[imu]")
// {
//     while (true) {
//         vector3_t data = read_accelerometer();
//         ESP_LOGI("test", "accelerometer: (%f, %f, %f) g", data.x, data.y, data.z);
//         vTaskDelay(pdMS_TO_TICKS(1000));
//     }
// }

// TEST_CASE("magnetometer", "[imu]")
// {
//     while (true) {
//         vector3_t data = read_magnetometer();
//         ESP_LOGI("test", "magnetometer: (%f, %f, %f) gauss", data.x, data.y, data.z);
//         vTaskDelay(pdMS_TO_TICKS(1000));
//     }
// }

// TEST_CASE("gyroscope", "[imu]")
// {
//     while (true) {
//         vector3_t data = read_gyroscope();
//         ESP_LOGI("test", "gyroscope: (%f, %f, %f) degrees per second", data.x, data.y, data.z);
//         vTaskDelay(pdMS_TO_TICKS(1000));
//     }
// }
