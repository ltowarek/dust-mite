#include "telemetry.hpp"
#include "unity.h"
#include <math.h>

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
