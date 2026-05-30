#include "telemetry_types.hpp"
#include "unity.h"

TEST_CASE("json_schema_completeness", "[telemetry_json]")
{
    telemetry_packet_t p = {"2024-01-15T10:30:00Z", -65, 2.5f,
                            {0.01f, 0.02f, 1.0f},
                            {0.1f, -0.2f, 0.05f},
                            {0.5f, -0.3f, 0.1f},
                            100};

    cJSON *j = convert_telemetry_packet_to_json(p);
    TEST_ASSERT_NOT_NULL(j);

    TEST_ASSERT_TRUE(cJSON_IsString(cJSON_GetObjectItem(j, "timestamp")));
    TEST_ASSERT_TRUE(cJSON_IsNumber(cJSON_GetObjectItem(j, "rssi")));
    TEST_ASSERT_TRUE(cJSON_IsNumber(cJSON_GetObjectItem(j, "speed")));
    TEST_ASSERT_TRUE(cJSON_IsNumber(cJSON_GetObjectItem(j, "distance_ahead")));

    const char *vector_keys[] = {"accelerometer", "magnetometer", "gyroscope"};
    for (int i = 0; i < 3; i++) {
        const cJSON *obj = cJSON_GetObjectItem(j, vector_keys[i]);
        TEST_ASSERT_NOT_NULL(obj);
        TEST_ASSERT_TRUE(cJSON_IsNumber(cJSON_GetObjectItem(obj, "x")));
        TEST_ASSERT_TRUE(cJSON_IsNumber(cJSON_GetObjectItem(obj, "y")));
        TEST_ASSERT_TRUE(cJSON_IsNumber(cJSON_GetObjectItem(obj, "z")));
    }

    cJSON_Delete(j);
}

TEST_CASE("json_value_roundtrip", "[telemetry_json]")
{
    telemetry_packet_t p = {"2024-01-15T10:30:00Z", -65, 0.0f,
                            {1.0f, 2.0f, 3.0f},
                            {}, {}, 100};

    cJSON *j = convert_telemetry_packet_to_json(p);
    TEST_ASSERT_NOT_NULL(j);

    TEST_ASSERT_EQUAL_STRING("2024-01-15T10:30:00Z",
        cJSON_GetStringValue(cJSON_GetObjectItem(j, "timestamp")));
    TEST_ASSERT_EQUAL_INT(-65,
        (int)cJSON_GetNumberValue(cJSON_GetObjectItem(j, "rssi")));
    TEST_ASSERT_EQUAL_INT(100,
        (int)cJSON_GetNumberValue(cJSON_GetObjectItem(j, "distance_ahead")));

    const cJSON *accel = cJSON_GetObjectItem(j, "accelerometer");
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 1.0f,
        (float)cJSON_GetNumberValue(cJSON_GetObjectItem(accel, "x")));
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 2.0f,
        (float)cJSON_GetNumberValue(cJSON_GetObjectItem(accel, "y")));
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 3.0f,
        (float)cJSON_GetNumberValue(cJSON_GetObjectItem(accel, "z")));

    cJSON_Delete(j);
}
