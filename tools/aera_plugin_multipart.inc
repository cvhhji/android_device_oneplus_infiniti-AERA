// Match prepare_aera_plugin_parts.py. The signed catalog still authenticates
// the assembled package and its size before installation.
constexpr uint64_t kPluginMirrorPartSize = 8ULL * 1024 * 1024;

bool DownloadGiteePluginParts(const std::string &url, const std::string &path,
                              uint64_t expected_size, Progress *progress,
                              unsigned progress_start, unsigned progress_end) {
  if (expected_size <= kPluginMirrorPartSize || expected_size > kMaxPayload)
    return false;
  const std::string assembled = path + ".assembling";
  const std::string chunk = path + ".chunk";
  unlink(path.c_str());
  unlink(assembled.c_str());
  unlink(chunk.c_str());
  const int output = open(assembled.c_str(),
                          O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW | O_CLOEXEC,
                          0600);
  if (output < 0) return false;
  uint64_t total = 0;
  bool ok = true;
  std::array<unsigned char, 65536> buffer{};
  const unsigned span = progress_end > progress_start
                            ? progress_end - progress_start : 0;
  if (progress) {
    progress->downloaded_bytes.store(0);
    progress->total_bytes.store(expected_size);
    progress->value.store(progress_start);
  }
  for (unsigned index = 0; total < expected_size && ok; ++index) {
    const uint64_t part_size =
        std::min<uint64_t>(kPluginMirrorPartSize, expected_size - total);
    if (!DownloadSingleUrl(url + ".part" + std::to_string(index), chunk,
                           part_size, nullptr, 0, 0, part_size)) {
      ok = false;
      break;
    }
    const int input = open(chunk.c_str(), O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    struct stat info{};
    if (input < 0 || fstat(input, &info) != 0 || !S_ISREG(info.st_mode) ||
        info.st_size < 0 || static_cast<uint64_t>(info.st_size) != part_size) {
      if (input >= 0) close(input);
      ok = false;
      break;
    }
    uint64_t copied = 0;
    while (ok && copied < part_size) {
      const size_t wanted =
          static_cast<size_t>(std::min<uint64_t>(buffer.size(), part_size - copied));
      const ssize_t count = read(input, buffer.data(), wanted);
      if (count < 0 && errno == EINTR) continue;
      if (count <= 0) {
        ok = false;
        break;
      }
      size_t offset = 0;
      while (offset < static_cast<size_t>(count)) {
        const ssize_t written = write(output, buffer.data() + offset,
                                       static_cast<size_t>(count) - offset);
        if (written < 0 && errno == EINTR) continue;
        if (written <= 0) {
          ok = false;
          break;
        }
        offset += static_cast<size_t>(written);
      }
      if (!ok) break;
      copied += static_cast<uint64_t>(count);
      total += static_cast<uint64_t>(count);
      if (progress) {
        progress->downloaded_bytes.store(total);
        progress->value.store(progress_start +
            static_cast<unsigned>(total * span / expected_size));
      }
    }
    close(input);
    unlink(chunk.c_str());
  }
  if (ok && total == expected_size) {
    if (fsync(output) != 0) ok = false;
  } else {
    ok = false;
  }
  if (close(output) != 0) ok = false;
  unlink(chunk.c_str());
  if (ok && rename(assembled.c_str(), path.c_str()) == 0) {
    if (progress) progress->value.store(progress_end);
    return true;
  }
  unlink(assembled.c_str());
  unlink(path.c_str());
  return false;
}

bool Download(const std::string &url, const std::string &path, uint64_t limit,
              Progress *progress = nullptr, unsigned progress_start = 0,
              unsigned progress_end = 0, uint64_t expected_size = 0) {
  const std::string primary = ResolvePrimaryDownloadUrl(url);
  if (primary.empty() || limit == 0 || limit > kMaxPayload || expected_size > limit)
    return false;
  const bool gitee =
      primary.compare(0, sizeof(kGiteePluginMirrorPrefix) - 1,
                       kGiteePluginMirrorPrefix) == 0;
  if (gitee && expected_size > kPluginMirrorPartSize) {
    if (DownloadGiteePluginParts(primary, path, expected_size, progress,
                                progress_start, progress_end))
      return true;
  } else if (DownloadSingleUrl(primary, path, limit, progress,
                               progress_start, progress_end, expected_size)) {
    return true;
  }
  const std::string fallback = ResolveFallbackDownloadUrl(url);
  if (!fallback.empty() &&
      DownloadSingleUrl(fallback, path, limit, progress,
                        progress_start, progress_end, expected_size))
    return true;
  // Screenshots and future store assets may not have been mirrored yet.
  if (OfficialUrl(url) && url != primary && url != fallback)
    return DownloadSingleUrl(url, path, limit, progress,
                              progress_start, progress_end, expected_size);
  return false;
}
