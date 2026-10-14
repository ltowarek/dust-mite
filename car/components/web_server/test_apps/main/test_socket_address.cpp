#include <cstring>
#include "socket_address.hpp"
#include "unity.h"

static sockaddr_storage ipv4_address(const char* host, uint16_t port) {
  sockaddr_storage storage = {};
  auto* address = reinterpret_cast<sockaddr_in*>(&storage);
  address->sin_family = AF_INET;
  address->sin_port = htons(port);
  inet_pton(AF_INET, host, &address->sin_addr);
  return storage;
}

static sockaddr_storage ipv6_address(const char* host, uint16_t port) {
  sockaddr_storage storage = {};
  auto* address = reinterpret_cast<sockaddr_in6*>(&storage);
  address->sin6_family = AF_INET6;
  address->sin6_port = htons(port);
  inet_pton(AF_INET6, host, &address->sin6_addr);
  return storage;
}

static socket_address_t formatted(const sockaddr_storage& address) {
  socket_address_t out = {};
  if (!socket_address_format(address, &out)) {
    TEST_FAIL_MESSAGE("the address was not formatted");
  }
  return out;
}

TEST_CASE("socket_address_formats_ipv4_host", "[socket_address]") {
  TEST_ASSERT_EQUAL_STRING("192.168.50.66", formatted(ipv4_address("192.168.50.66", 81)).host);
}

TEST_CASE("socket_address_formats_port_in_host_order", "[socket_address]") {
  TEST_ASSERT_EQUAL_UINT16(81, formatted(ipv4_address("192.168.50.66", 81)).port);
}

TEST_CASE("socket_address_unmaps_ipv4_mapped_ipv6_host", "[socket_address]") {
  TEST_ASSERT_EQUAL_STRING("192.168.50.10",
                           formatted(ipv6_address("::ffff:192.168.50.10", 50000)).host);
}

TEST_CASE("socket_address_formats_ipv6_host", "[socket_address]") {
  TEST_ASSERT_EQUAL_STRING("fe80::1", formatted(ipv6_address("fe80::1", 50000)).host);
}

TEST_CASE("socket_address_rejects_unknown_family", "[socket_address]") {
  sockaddr_storage unknown = {};
  socket_address_t out = {};
  TEST_ASSERT_FALSE(socket_address_format(unknown, &out));
}
