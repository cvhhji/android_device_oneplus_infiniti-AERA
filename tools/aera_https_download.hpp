// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <algorithm>
#include <cerrno>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <functional>
#include <poll.h>
#include <string>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include <vector>

namespace aera_https {

inline uint64_t MonotonicMs() {
  timespec now{};
  clock_gettime(CLOCK_MONOTONIC, &now);
  return static_cast<uint64_t>(now.tv_sec) * 1000 + now.tv_nsec / 1000000;
}

inline void CloseOtherDescriptors(int keep, int maximum) {
#if defined(__NR_close_range)
  const bool low = keep <= 3 || syscall(__NR_close_range, 3U,
                                       static_cast<unsigned>(keep - 1), 0U) == 0;
  const bool high = syscall(__NR_close_range,
                            static_cast<unsigned>(keep + 1), ~0U, 0U) == 0;
  if (low && high) return;
#endif
  for (int fd = 3; fd < maximum; ++fd)
    if (fd != keep) close(fd);
}

// A supervisor reports curl's actual status through a CLOEXEC pipe. Recovery's
// global SIGCHLD reaper cannot steal this status, and curl cannot inherit the
// UI's display, input, socket, or completion descriptors. Killing the dedicated
// process group also cleans up descendants on cancellation or a hard deadline.
inline bool Download(const std::string &url, const std::string &path,
                     uint64_t maximum, uint64_t expected_size,
                     const std::function<void(uint64_t)> &progress,
                     const std::function<bool()> &cancelled,
                     unsigned attempts, uint64_t timeout_ms) {
  constexpr char curl[] = "/system/bin/curl";
  constexpr char certificates[] = "/system/etc/security/aera-cacert.pem";
  if (url.compare(0, 8, "https://") != 0 || maximum == 0 ||
      expected_size > maximum || timeout_ms == 0 ||
      access(curl, X_OK) != 0 || access(certificates, R_OK) != 0)
    return false;
  const std::string max_size = std::to_string(maximum);
  const std::string seconds = std::to_string((timeout_ms + 999) / 1000);
  const std::string diagnostics = path + ".download.log";
  // AERA's Bionic recovery resolver honors RES_OPTIONS. Bound DNS separately
  // so an unresponsive DHCP resolver cannot consume the whole transfer budget.
  std::vector<std::string> variables;
  for (char **item = ::environ; item != nullptr && *item != nullptr; ++item)
    if (strncmp(*item, "RES_OPTIONS=", 12) != 0) variables.emplace_back(*item);
  variables.emplace_back("RES_OPTIONS=timeout:2 attempts:2");
  std::vector<char *> environment;
  for (const auto &variable : variables)
    environment.push_back(const_cast<char *>(variable.c_str()));
  environment.push_back(nullptr);
  const char *arguments[] = {
      curl, "--disable", "--fail", "--location", "--silent", "--show-error",
      "--ipv4", "--proto", "=https", "--proto-redir", "=https",
      "--max-redirs", "5", "--cacert", certificates,
      "--connect-timeout", "15", "--max-time", seconds.c_str(),
      "--speed-limit", "1024", "--speed-time", "30",
      "--continue-at", "-",
      "--max-filesize", max_size.c_str(), "--output", path.c_str(),
      url.c_str(), nullptr};
  const long open_maximum = sysconf(_SC_OPEN_MAX);
  const int maximum_fd = open_maximum > 0 ? static_cast<int>(open_maximum) : 65536;

  for (unsigned attempt = 0; attempt < attempts && !cancelled(); ++attempt) {
    // Packages have a signed, fixed size and hash. Resume a partial package
    // after a transient failure instead of repeatedly discarding slow links.
    if (attempt == 0 || expected_size <= 1024 * 1024) unlink(path.c_str());
    unlink(diagnostics.c_str());
    int completion[2];
    if (pipe2(completion, O_CLOEXEC) != 0) return false;
    const pid_t supervisor = fork();
    if (supervisor < 0) {
      close(completion[0]);
      close(completion[1]);
      return false;
    }
    if (supervisor == 0) {
      close(completion[0]);
      if (setpgid(0, 0) != 0) _exit(126);
      struct sigaction action{};
      action.sa_handler = SIG_DFL;
      sigemptyset(&action.sa_mask);
      for (int signal_number : {SIGCHLD, SIGPIPE, SIGALRM, SIGINT, SIGTERM,
                                SIGHUP, SIGXFSZ})
        sigaction(signal_number, &action, nullptr);
      sigset_t empty;
      sigemptyset(&empty);
      sigprocmask(SIG_SETMASK, &empty, nullptr);
      CloseOtherDescriptors(completion[1], maximum_fd);
      const int null_fd = open("/dev/null", O_RDWR);
      const int error_fd = open(diagnostics.c_str(),
          O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW | O_CLOEXEC, 0600);
      if (null_fd < 0 || error_fd < 0 ||
          dup2(null_fd, STDIN_FILENO) < 0 ||
          dup2(null_fd, STDOUT_FILENO) < 0 ||
          dup2(error_fd, STDERR_FILENO) < 0)
        _exit(126);
      if (null_fd > STDERR_FILENO) close(null_fd);
      if (error_fd > STDERR_FILENO) close(error_fd);
      rlimit size{maximum, maximum};
      if (setrlimit(RLIMIT_FSIZE, &size) != 0) _exit(126);
      umask(077);
      const pid_t transfer = fork();
      if (transfer < 0) _exit(126);
      if (transfer == 0) {
        close(completion[1]);
        execve(curl, const_cast<char *const *>(arguments), environment.data());
        _exit(127);
      }
      int status = 0;
      pid_t waited;
      do {
        waited = waitpid(transfer, &status, 0);
      } while (waited < 0 && errno == EINTR);
      if (waited == transfer) {
        ssize_t result;
        do {
          result = write(completion[1], &status, sizeof(status));
        } while (result < 0 && errno == EINTR);
      }
      _exit(0);
    }

    close(completion[1]);
    // The child establishes its group too, before forking curl.
    setpgid(supervisor, supervisor);
    const uint64_t started = MonotonicMs();
    pollfd event{completion[0], POLLIN | POLLHUP, 0};
    int status = 0;
    bool reported = false;
    bool aborted = false;
    while (true) {
      if (cancelled() || MonotonicMs() - started >= timeout_ms + 2000) {
        aborted = true;
        break;
      }
      const int result = poll(&event, 1, 100);
      if (result < 0 && errno == EINTR) continue;
      if (result < 0) break;
      if (event.revents & POLLIN) {
        reported = read(completion[0], &status, sizeof(status)) ==
                   static_cast<ssize_t>(sizeof(status));
        break;
      }
      if (event.revents & (POLLHUP | POLLERR | POLLNVAL)) break;
      struct stat partial{};
      if (lstat(path.c_str(), &partial) == 0 && S_ISREG(partial.st_mode) &&
          partial.st_size >= 0)
        progress(static_cast<uint64_t>(partial.st_size));
    }
    close(completion[0]);
    kill(-supervisor, SIGKILL);
    // Covers failure before the child could establish its process group.
    if (!reported) kill(supervisor, SIGKILL);
    // A single WNOHANG check races with the supervisor's exit and leaves a
    // zombie after each download. SIGKILL above makes this wait finite; a
    // global reaper may already have collected the child (ECHILD is fine).
    pid_t reaped;
    do {
      reaped = waitpid(supervisor, nullptr, 0);
    } while (reaped < 0 && errno == EINTR);
    struct stat info{};
    if (!aborted && reported && WIFEXITED(status) && WEXITSTATUS(status) == 0 &&
        lstat(path.c_str(), &info) == 0 && S_ISREG(info.st_mode) &&
        info.st_size > 0 && static_cast<uint64_t>(info.st_size) <= maximum &&
        (expected_size == 0 || static_cast<uint64_t>(info.st_size) == expected_size)) {
      progress(static_cast<uint64_t>(info.st_size));
      unlink(diagnostics.c_str());
      return true;
    }
    char error[1025]{};
    const int error_fd = open(diagnostics.c_str(), O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (error_fd >= 0) {
      const ssize_t count = read(error_fd, error, sizeof(error) - 1);
      if (count > 0) error[count] = '\0';
      close(error_fd);
    }
    fprintf(stderr, "AERA HTTPS: %s attempt %u failed (status=%d timeout=%d): %s\n",
            path.c_str(), attempt + 1, reported ? status : -1, aborted, error);
    // CURLE_RANGE_ERROR: a server without Range support needs a clean retry.
    if (reported && WIFEXITED(status) && WEXITSTATUS(status) == 33)
      unlink(path.c_str());
  }
  unlink(path.c_str());
  return false;
}

}  // namespace aera_https
