#pragma once

#include <cstdint>
#include "lwip/sockets.h"

struct socket_address_t {
  char host[INET6_ADDRSTRLEN];
  uint16_t port;
};

// Formats an address as OpenTelemetry's *.address and *.port attributes record it. httpd listens
// on an IPv6 socket, so an IPv4 peer arrives IPv4-mapped (::ffff:a.b.c.d) and is written as IPv4.
bool socket_address_format(const sockaddr_storage& address, socket_address_t* out);
