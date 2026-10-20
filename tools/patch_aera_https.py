#!/usr/bin/env python3
"""Install a bounded, certificate-verifying transport in AERA cloud sources."""

from pathlib import Path
import sys


def replace_function(text: str, start: str, end: str, replacement: str) -> str:
    first = text.find(start)
    last = text.find(end, first)
    if (first < 0 or last < 0 or text.count(start) != 1
            or text.count(end) != 1):
        raise SystemExit(f"Could not locate the AERA transfer function: {start}")
    return text[:first] + replacement.rstrip() + "\n\n" + text[last:]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <AERA source root>")
    root = Path(sys.argv[1])
    recovery = root / "bootable/recovery"
    header = recovery / "aeraui/aera_https_download.hpp"
    header.write_bytes(Path(__file__).with_name(header.name).read_bytes())
    include = '#include "../../aera_https_download.hpp"\n'
    plugins_path = recovery / "aeraui/features/plugins/plugin_manager.cpp"
    plugins = plugins_path.read_text(encoding="utf-8")
    if include not in plugins:
        plugins = include + plugins
    plugins = replace_function(
        plugins,
        "bool DownloadSingleUrl(",
        "// Match prepare_aera_plugin_parts.py.",
        '''bool DownloadSingleUrl(const std::string &url, const std::string &path,
                       uint64_t limit, Progress *progress = nullptr,
                       unsigned progress_start = 0, unsigned progress_end = 0,
                       uint64_t expected_size = 0, uint64_t offset = 0,
                       uint64_t overall_size = 0) {
  if (limit == 0 || limit > kMaxPayload || expected_size > limit) return false;
  const uint64_t total = overall_size != 0 ? overall_size : expected_size;
  if (total != 0 && (offset > total || expected_size > total - offset))
    return false;
  const unsigned span = progress_end > progress_start
                            ? progress_end - progress_start : 0;
  uint64_t reported = offset;
  const auto report = [&](uint64_t bytes) {
    if (!progress || total == 0) return;
    reported = std::max(reported, offset + std::min(bytes, expected_size));
    progress->total_bytes.store(total);
    progress->downloaded_bytes.store(reported);
    progress->value.store(progress_start +
        static_cast<unsigned>(reported * span / total));
  };
  report(0);
  return aera_https::Download(url, path, limit, expected_size, report,
      [] { return false; }, 2, limit <= kMaxCatalog ? 45000 : 900000);
}''',
    )
    if plugins.count("                           total, expected_size))") != 1:
        raise SystemExit("Plugin multipart download is missing its whole-package offset")
    plugins_path.write_text(plugins, encoding="utf-8", newline="\n")

    updater_path = recovery / "aeraui/features/update/update_manager.cpp"
    updater = updater_path.read_text(encoding="utf-8")
    if include not in updater:
        updater = include + updater
    updater = replace_function(
        updater,
        "bool DownloadFile(",
        "bool ReadCatalog(",
        '''bool DownloadFile(const std::string &url, const std::string &path,
                  uint64_t maximum, uint64_t expected_size,
                  unsigned progress_start, unsigned progress_end,
                  unsigned max_attempts = 2,
                  uint64_t timeout_override_ms = 0,
                  uint64_t completed_bytes = 0,
                  uint64_t overall_size = 0) {
  if (!SafeHttps(url) || maximum == 0) return false;
  const uint64_t total = overall_size != 0 ? overall_size : expected_size;
  if (total != 0 && (completed_bytes > total ||
                    expected_size > total - completed_bytes)) return false;
  const uint64_t timeout_ms = timeout_override_ms != 0
      ? timeout_override_ms : (maximum <= kMaxCatalog ? 45000 : 900000);
  const unsigned span = progress_end > progress_start
                            ? progress_end - progress_start : 0;
  uint64_t reported = completed_bytes;
  const auto report = [&](uint64_t bytes) {
    if (total == 0) return;
    reported = std::max(reported,
        completed_bytes + std::min(bytes, expected_size));
    gDownloaded.store(reported);
    gTotal.store(total);
    gProgress.store(progress_start +
        static_cast<unsigned>(reported * span / total));
  };
  report(0);
  return aera_https::Download(url, path, maximum, expected_size, report,
      [] { return gCancel.load(); }, max_attempts, timeout_ms);
}''',
    )
    updater_path.write_text(updater, encoding="utf-8", newline="\n")

    wlan_path = recovery / "wlan.cpp"
    wlan = wlan_path.read_text(encoding="utf-8")
    old_dns = 'for (const char* fallback : {"1.1.1.1", "8.8.8.8"}) {'
    new_dns = ('for (const char* fallback : '
               '{"223.5.5.5", "119.29.29.29", "1.1.1.1", "8.8.8.8"}) {')
    if old_dns not in wlan and new_dns not in wlan:
        raise SystemExit("Could not locate the WLAN fallback DNS list")
    wlan = wlan.replace(old_dns, new_dns)
    old_properties = '''    if (!servers.empty()) {
        property_set("net.dns1", servers[0].c_str());
        if (servers.size() > 1)
            property_set("net.dns2", servers[1].c_str());
    }'''
    new_properties = '''    // Keep Android-property and resolv.conf consumers consistent. DHCP DNS
    // remains first; mainland resolvers precede overseas public fallbacks.
    for (size_t index = 0; index < 4; ++index) {
        const std::string key = "net.dns" + std::to_string(index + 1);
        property_set(key.c_str(), index < servers.size() ? servers[index].c_str() : "");
    }'''
    if old_properties not in wlan and new_properties not in wlan:
        raise SystemExit("Could not locate the WLAN DNS properties")
    wlan = wlan.replace(old_properties, new_properties)
    wlan_path.write_text(wlan, encoding="utf-8", newline="\n")
    print("AERA plugins and OTA use curl with verified TLS, IPv4, explicit status, "
          "bounded retries, process-group cleanup, and cumulative whole-package progress.")


if __name__ == "__main__":
    main()
