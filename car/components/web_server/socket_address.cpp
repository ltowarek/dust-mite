#include "socket_address.hpp"
#include <cctype>

bool socket_address_format(const sockaddr_storage& address, socket_address_t* out) {
  if (address.ss_family == AF_INET) {
    const auto& ipv4 = reinterpret_cast<const sockaddr_in&>(address);
    out->port = ntohs(ipv4.sin_port);
    return inet_ntop(AF_INET, &ipv4.sin_addr, out->host, sizeof(out->host)) != nullptr;
  }
  if (address.ss_family != AF_INET6) {
    return false;
  }
  const auto& ipv6 = reinterpret_cast<const sockaddr_in6&>(address);
  out->port = ntohs(ipv6.sin6_port);
  if (IN6_IS_ADDR_V4MAPPED(&ipv6.sin6_addr)) {
    const int ipv4_offset = 12;
    return inet_ntop(AF_INET, &ipv6.sin6_addr.s6_addr[ipv4_offset], out->host, sizeof(out->host)) !=
           nullptr;
  }
  if (inet_ntop(AF_INET6, &ipv6.sin6_addr, out->host, sizeof(out->host)) == nullptr) {
    return false;
  }
  // lwIP writes hex digits in upper case; RFC 5952 text form is lower case.
  for (char* c = out->host; *c != '\0'; ++c) {
    *c = static_cast<char>(std::tolower(static_cast<unsigned char>(*c)));
  }
  return true;
}
