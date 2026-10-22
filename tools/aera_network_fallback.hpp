// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <algorithm>
#include <arpa/inet.h>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <functional>
#include <map>
#include <mutex>
#include <poll.h>
#include <set>
#include <sstream>
#include <string>
#include <sys/random.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/vfs.h>
#include <time.h>
#include <unistd.h>
#include <vector>

// A DNS answer selects a connection endpoint, never a TLS identity. Callers
// retain the HTTPS URL/SNI and must verify its certificate before Remember().
namespace aera_network {
inline uint64_t NowMs() {
  timespec now{};
  clock_gettime(CLOCK_MONOTONIC, &now);
  return uint64_t(now.tv_sec) * 1000 + now.tv_nsec / 1000000;
}
struct Address {
  std::string ip;
  uint64_t expires = 0;
};
inline std::string GithubHost(const std::string &url) {
  if (url.compare(0, 8, "https://") || url.size() > 2048) return {};
  std::string host = url.substr(8, url.find_first_of("/?#", 8) - 8);
  if (host.size() > 4 && host.compare(host.size() - 4, 4, ":443") == 0)
    host.resize(host.size() - 4);
  if (host.empty() || host.size() > 253) return {};
  for (char &c : host) {
    if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
    if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '.' || c == '-'))
      return {};
  }
  for (const char *base : {"github.com", "githubusercontent.com", "githubassets.com"}) {
    const size_t size = strlen(base);
    if (host == base || (host.size() > size &&
        host[host.size() - size - 1] == '.' &&
        host.compare(host.size() - size, size, base) == 0)) return host;
  }
  return {};
}
inline bool PublicAddress(const std::string &ip) {
  in_addr v4{};
  if (inet_pton(AF_INET, ip.c_str(), &v4) == 1) {
    const uint32_t n = ntohl(v4.s_addr);
    return (n >> 24) != 0 && (n >> 24) != 10 && (n >> 24) != 127 &&
        (n >> 16) != 0xa9fe && (n >> 20) != 0xac1 &&
        (n >> 16) != 0xc0a8 && (n >> 22) != 0x191 && n < 0xe0000000U;
  }
  in6_addr v6{};
  if (inet_pton(AF_INET6, ip.c_str(), &v6) != 1) return false;
  // Accept global unicast. Loopback, link-local, ULA and mapped IPv4 cannot
  // turn a public GitHub retry into an internal-network probe.
  return (v6.s6_addr[0] & 0xe0) == 0x20;
}
inline bool ReadName(const std::vector<uint8_t> &data, size_t &cursor, std::string &name) {
  size_t at = cursor;
  bool jumped = false;
  name.clear();
  for (unsigned hops = 0; hops < 64; ++hops) {
    if (at >= data.size()) return false;
    unsigned count = data[at++];
    if (!count) {
      if (!jumped) cursor = at;
      return name.size() <= 253;
    }
    if ((count & 0xc0) == 0xc0) {
      if (at >= data.size()) return false;
      const size_t target = ((count & 63) << 8) | data[at++];
      if (!jumped) cursor = at;
      jumped = true;
      at = target;
      continue;
    }
    if (count > 63 || at + count > data.size()) return false;
    if (!name.empty()) name += '.';
    for (unsigned i = 0; i < count; ++i) {
      char c = static_cast<char>(data[at++]);
      if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
      if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-'))
        return false;
      name += c;
    }
    if (name.size() > 253) return false;
  }
  return false;
}
inline uint16_t U16(const std::vector<uint8_t> &data, size_t at) {
  return (uint16_t(data[at]) << 8) | data[at + 1];
}
inline std::vector<Address> ParseReply(const std::vector<uint8_t> &data,
    uint16_t id, const std::string &host, uint16_t query_type) {
  if (data.size() < 12 || U16(data, 0) != id || !(data[2] & 0x80) ||
      (data[2] & 0x7a) || (data[3] & 15) || U16(data, 4) != 1 || U16(data, 6) > 64)
    return {};
  size_t cursor = 12;
  std::string name;
  if (!ReadName(data, cursor, name) || name != host || cursor + 4 > data.size() ||
      U16(data, cursor) != query_type || U16(data, cursor + 2) != 1) return {};
  cursor += 4;
  struct Record { std::string owner, target, ip; uint32_t ttl = 0; };
  std::vector<Record> records;
  for (unsigned i = 0; i < U16(data, 6); ++i) {
    Record record;
    if (!ReadName(data, cursor, record.owner) || cursor + 10 > data.size()) return {};
    const unsigned type = U16(data, cursor), cls = U16(data, cursor + 2);
    record.ttl = (uint32_t(data[cursor + 4]) << 24) | (uint32_t(data[cursor + 5]) << 16) |
                 (uint32_t(data[cursor + 6]) << 8) | data[cursor + 7];
    const unsigned size = U16(data, cursor + 8);
    cursor += 10;
    if (cursor + size > data.size()) return {};
    if (cls == 1 && type == 5) {
      size_t next = cursor;
      if (!ReadName(data, next, record.target) || next != cursor + size) return {};
    } else if (cls == 1 && ((type == 1 && size == 4) || (type == 28 && size == 16))) {
      char text[INET6_ADDRSTRLEN]{};
      if (inet_ntop(type == 1 ? AF_INET : AF_INET6, data.data() + cursor, text, sizeof(text)))
        record.ip = text;
    }
    records.push_back(record);
    cursor += size;
  }
  std::set<std::string> owners{host};
  uint32_t ttl = 300;
  for (unsigned i = 0; i < 8; ++i)
    for (const auto &record : records)
      if (owners.count(record.owner) && !record.target.empty()) {
        owners.insert(record.target);
        ttl = std::min(ttl, record.ttl);
      }
  std::vector<Address> result;
  for (const auto &record : records)
    if (owners.count(record.owner) && PublicAddress(record.ip))
      result.push_back({record.ip, NowMs() + uint64_t(std::min(ttl, record.ttl)) * 1000});
  return result;
}
inline std::vector<std::string> ResolverServers() {
  // These are resolver services, not fixed GitHub endpoints. Normal traffic
  // still uses DHCP; this list is consulted only after a network failure.
  std::vector<std::string> result{"1.1.1.1", "8.8.8.8"};
  std::ifstream input("/etc/resolv.conf");
  std::string line;
  while (result.size() < 6 && std::getline(input, line)) {
    std::istringstream row(line);
    std::string key, value;
    row >> key >> value;
    in_addr v4{}; in6_addr v6{};
    if (key == "nameserver" &&
        (inet_pton(AF_INET, value.c_str(), &v4) == 1 ||
         inet_pton(AF_INET6, value.c_str(), &v6) == 1) &&
        std::find(result.begin(), result.end(), value) == result.end()) result.push_back(value);
  }
  return result;
}
inline std::vector<Address> Query(const std::string &host, const std::string &server,
    uint16_t type, const std::function<bool()> &cancelled) {
  uint16_t id;
  if (getrandom(&id, sizeof(id), GRND_NONBLOCK) != static_cast<ssize_t>(sizeof(id)))
    return {};
  std::vector<uint8_t> query{uint8_t(id >> 8), uint8_t(id), 1, 0, 0, 1, 0, 0, 0, 0, 0, 0};
  size_t start = 0;
  while (start < host.size()) {
    size_t end = host.find('.', start);
    if (end == std::string::npos) end = host.size();
    if (end == start || end - start > 63) return {};
    query.push_back(static_cast<uint8_t>(end - start));
    query.insert(query.end(), host.begin() + start, host.begin() + end);
    start = end + 1;
  }
  query.insert(query.end(), {0, uint8_t(type >> 8), uint8_t(type), 0, 1});
  sockaddr_storage target{};
  auto *v4 = reinterpret_cast<sockaddr_in *>(&target);
  auto *v6 = reinterpret_cast<sockaddr_in6 *>(&target);
  const bool ipv4 = inet_pton(AF_INET, server.c_str(), &v4->sin_addr) == 1;
  if (ipv4) { v4->sin_family = AF_INET; v4->sin_port = htons(53); }
  else {
    if (inet_pton(AF_INET6, server.c_str(), &v6->sin6_addr) != 1) return {};
    v6->sin6_family = AF_INET6; v6->sin6_port = htons(53);
  }
  const int fd = socket(ipv4 ? AF_INET : AF_INET6, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
  if (fd < 0) return {};
  const socklen_t size = static_cast<socklen_t>(ipv4 ? sizeof(sockaddr_in) : sizeof(sockaddr_in6));
  std::vector<Address> result;
  if (connect(fd, reinterpret_cast<sockaddr *>(&target), size) == 0 &&
      send(fd, query.data(), query.size(), MSG_NOSIGNAL) == static_cast<ssize_t>(query.size())) {
    const uint64_t until = NowMs() + 700;
    while (!cancelled() && NowMs() < until) {
      pollfd event{fd, POLLIN, 0};
      if (poll(&event, 1, 50) > 0 && (event.revents & POLLIN)) {
        std::vector<uint8_t> reply(4096);
        const ssize_t count = recv(fd, reply.data(), reply.size(), MSG_TRUNC);
        if (count > 0 && static_cast<size_t>(count) <= reply.size()) {
          reply.resize(static_cast<size_t>(count));
          result = ParseReply(reply, id, host, type);
        }
        break;
      }
    }
  }
  close(fd);
  return result;
}
inline std::string BrowserResolverPath(const std::string &runtime) {
  struct stat info{};
  struct statfs filesystem{};
  // Match the upstream jail's live read-only resolver mount. Otherwise use
  // the resolver file created inside this private runtime at launch.
  if (!lstat("/etc/resolv.conf", &info) && S_ISREG(info.st_mode) &&
      info.st_uid == 0 && !statfs("/etc/resolv.conf", &filesystem) &&
      (filesystem.f_type == 0x01021994 || filesystem.f_type == 0x858458f6))
    return "/etc/resolv.conf";
  return runtime + "/etc/resolv.conf";
}
inline std::vector<Address> PrimaryAddresses(const std::string &url,
    const std::string &resolver_file,
    const std::function<bool()> &cancelled) {
  const std::string host = GithubHost(url);
  if (host.empty()) return {};
  std::ifstream input(resolver_file);
  std::string line;
  while (!cancelled() && std::getline(input, line)) {
    std::istringstream row(line);
    std::string key, server;
    row >> key >> server;
    in_addr v4{}; in6_addr v6{};
    if (key != "nameserver" ||
        (inet_pton(AF_INET, server.c_str(), &v4) != 1 &&
         inet_pton(AF_INET6, server.c_str(), &v6) != 1)) continue;
    // Identify the browser jail's own primary resolver after a failure.
    // Each query keeps its existing deadline; global resolver state is untouched.
    auto result = Query(host, server, 1, cancelled);
    const auto ipv6 = Query(host, server, 28, cancelled);
    result.insert(result.end(), ipv6.begin(), ipv6.end());
    return result;
  }
  return {};
}
inline std::vector<Address> Candidates(const std::string &url,
    const std::function<bool()> &cancelled) {
  const std::string host = GithubHost(url);
  if (host.empty()) return {};
  std::vector<Address> result;
  for (const auto &server : ResolverServers()) {
    if (cancelled() || result.size() >= 8) break;
    const auto ipv4 = Query(host, server, 1, cancelled);
    const auto ipv6 = Query(host, server, 28, cancelled);
    for (size_t i = 0; i < std::max(ipv4.size(), ipv6.size()); ++i) {
      std::vector<Address> next;
      if (i < ipv4.size()) next.push_back(ipv4[i]);
      if (i < ipv6.size()) next.push_back(ipv6[i]);
      for (const auto &candidate : next)
        if (std::none_of(result.begin(), result.end(), [&](const Address &old) {
              return old.ip == candidate.ip;
            })) result.push_back(candidate);
    }
  }
  if (result.size() > 8) result.resize(8);
  return result;
}
struct Routes {
  std::mutex mutex;
  std::map<std::string, Address> values;
};
inline Routes &RouteCache() { static Routes routes; return routes; }
inline Address Cached(const std::string &host) {
  auto &routes = RouteCache();
  std::lock_guard<std::mutex> lock(routes.mutex);
  auto found = routes.values.find(host);
  if (found == routes.values.end()) return {};
  if (found->second.expires <= NowMs()) { routes.values.erase(found); return {}; }
  return found->second;
}
inline void Forget(const std::string &host) {
  auto &routes = RouteCache();
  std::lock_guard<std::mutex> lock(routes.mutex);
  routes.values.erase(host);
}
inline void Remember(const std::string &url, Address address) {
  const std::string host = GithubHost(url);
  if (host.empty() || !PublicAddress(address.ip) || address.expires <= NowMs()) return;
  address.expires = std::min(address.expires, NowMs() + 300000);
  auto &routes = RouteCache();
  std::lock_guard<std::mutex> lock(routes.mutex);
  if (routes.values.size() >= 16 && !routes.values.count(host)) routes.values.erase(routes.values.begin());
  routes.values[host] = address;
}
inline std::map<std::string, Address> Snapshot() {
  auto &routes = RouteCache();
  std::lock_guard<std::mutex> lock(routes.mutex);
  for (auto it = routes.values.begin(); it != routes.values.end();)
    if (it->second.expires <= NowMs()) it = routes.values.erase(it);
    else ++it;
  return routes.values;
}
inline bool BrowserHosts(const std::string &runtime, bool launching = false) {
  if (runtime.size() != 20 || runtime.compare(0, 14, "/tmp/aera-web-")) return false;
  const int root = open(runtime.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  struct stat info{};
  if (root < 0) return false;
  // The jail makes its root traversable by the isolated UID. After that
  // supervisor exits, restore the launcher's private-directory invariant.
  if (fstat(root, &info) || info.st_uid ||
      ((info.st_mode & 0777) != 0700 && (info.st_mode & 0777) != 0755) ||
      (launching && fchmod(root, 0700))) { close(root); return false; }
  const int etc = openat(root, "etc", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  close(root);
  if (etc < 0) return false;
  if (fstat(etc, &info) || info.st_uid || (info.st_mode & 0022)) { close(etc); return false; }
  const int fd = openat(etc, "hosts", O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0644);
  close(etc);
  if (fd < 0) return false;
  if (fstat(fd, &info) || !S_ISREG(info.st_mode) || info.st_uid || info.st_nlink != 1 ||
      (info.st_mode & 0022) || info.st_size > 32768) { close(fd); return false; }
  if (fchmod(fd, 0644)) { close(fd); return false; }
  std::string old(static_cast<size_t>(info.st_size), '\0');
  size_t read_bytes = 0;
  while (read_bytes < old.size()) {
    const ssize_t count = read(fd, &old[read_bytes], old.size() - read_bytes);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) { close(fd); return false; }
    read_bytes += static_cast<size_t>(count);
  }
  constexpr char begin[] = "# AERA temporary network routes\n";
  constexpr char end[] = "# AERA temporary network routes end\n";
  std::string text = old;
  const size_t first = text.find(begin);
  if (first != std::string::npos) {
    const size_t last = text.find(end, first + strlen(begin));
    if (last == std::string::npos) { close(fd); return false; }
    text.erase(first, last + strlen(end) - first);
  }
  if (!text.empty() && text.back() != '\n') text += '\n';
  text += begin;
  auto &routes = RouteCache();
  {
    std::lock_guard<std::mutex> lock(routes.mutex);
    for (auto it = routes.values.begin(); it != routes.values.end();) {
      if (it->second.expires <= NowMs()) it = routes.values.erase(it);
      else { text += it->second.ip + " " + it->first + "\n"; ++it; }
    }
  }
  text += end;
  bool ok = true;
  if (text != old) {
    ok = ftruncate(fd, 0) == 0 && lseek(fd, 0, SEEK_SET) == 0;
    size_t written = 0;
    while (ok && written < text.size()) {
      const ssize_t count = write(fd, text.data() + written, text.size() - written);
      if (count < 0 && errno == EINTR) continue;
      if (count <= 0) ok = false;
      else written += static_cast<size_t>(count);
    }
  }
  close(fd);
  return ok;
}
}  // namespace aera_network
