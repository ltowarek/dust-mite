#include "web_server.hpp"
#include "unity.h"

TEST_CASE("parse_valid_command_and_value", "[web_server]") {
  command_packet_t p = {};
  TEST_ASSERT_TRUE(parse_command_packet("{\"command\":3,\"value\":50}", &p));
  TEST_ASSERT_EQUAL_INT(3, p.command);
  TEST_ASSERT_EQUAL_INT(50, p.value);
}

TEST_CASE("parse_missing_value_defaults_zero", "[web_server]") {
  command_packet_t p = {};
  TEST_ASSERT_TRUE(parse_command_packet("{\"command\":2}", &p));
  TEST_ASSERT_EQUAL_INT(2, p.command);
  TEST_ASSERT_EQUAL_INT(0, p.value);
}

TEST_CASE("parse_missing_command_field", "[web_server]") {
  // cJSON_GetNumberValue(NULL) returns 0.0, so command=0 (out of valid range 1-7).
  // This test pins the current behavior; a future fix to reject it would change the assertion.
  command_packet_t p = {};
  TEST_ASSERT_TRUE(parse_command_packet("{\"value\":50}", &p));
  TEST_ASSERT_EQUAL_INT(0, p.command);
  TEST_ASSERT_EQUAL_INT(50, p.value);
}

TEST_CASE("parse_malformed_json", "[web_server]") {
  command_packet_t p = {};
  TEST_ASSERT_FALSE(parse_command_packet("{not json}", &p));
}

TEST_CASE("parse_null_input", "[web_server]") {
  command_packet_t p = {};
  TEST_ASSERT_FALSE(parse_command_packet(nullptr, &p));
}
