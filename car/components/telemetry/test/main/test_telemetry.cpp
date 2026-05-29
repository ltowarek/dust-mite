#include "telemetry.hpp"
#include "unity.h"
#include <math.h>
#include "driver/gpio.h"

extern "C" void app_main(void)
{
    i2c_master_bus_config_t bus_cfg = {};
    bus_cfg.i2c_port = I2C_NUM_0;
    bus_cfg.sda_io_num = GPIO_NUM_1;
    bus_cfg.scl_io_num = GPIO_NUM_2;
    bus_cfg.clk_source = I2C_CLK_SRC_DEFAULT;
    bus_cfg.glitch_ignore_cnt = 7;
    bus_cfg.flags.enable_internal_pullup = true;
    i2c_master_bus_handle_t i2c_bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &i2c_bus));
    telemetry_init(i2c_bus);

    UNITY_BEGIN();
    unity_run_all_tests();
    UNITY_END();
}

void setUp(void) {}
void tearDown(void) {}

TEST_CASE("speed", "[pcnt]")
{
    TEST_ASSERT_GREATER_OR_EQUAL_FLOAT(0.0f, get_speed());
}

TEST_CASE("accelerometer", "[imu]")
{
    vector3_t d = read_accelerometer();
    float mag = sqrtf(d.x * d.x + d.y * d.y + d.z * d.z);
    TEST_ASSERT_FLOAT_WITHIN(0.5f, 1.0f, mag);
}

TEST_CASE("magnetometer", "[imu]")
{
    vector3_t d = read_magnetometer();
    float mag = sqrtf(d.x * d.x + d.y * d.y + d.z * d.z);
    TEST_ASSERT_GREATER_THAN_FLOAT(0.0f, mag);
}

TEST_CASE("gyroscope", "[imu]")
{
    vector3_t d = read_gyroscope();
    TEST_ASSERT_FLOAT_WITHIN(5.0f, 0.0f, d.x);
    TEST_ASSERT_FLOAT_WITHIN(5.0f, 0.0f, d.y);
    TEST_ASSERT_FLOAT_WITHIN(5.0f, 0.0f, d.z);
}

TEST_CASE("distance", "[urm]")
{
    TEST_ASSERT_GREATER_THAN(0, get_distance_ahead());
}
