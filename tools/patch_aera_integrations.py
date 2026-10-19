#!/usr/bin/env python3
"""Point AERA OTA and signed plugin downloads at the owner's Gitee mirror.

Gitee raw asset branches and release assets are the primary endpoints for
mainland networks. GitHub Releases remain the fallback where Gitee is slow or
unavailable.
"""

from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0 and new in text:
        return text
    if count != 1:
        raise SystemExit(f"Expected one source match for {label}; found {count}")
    return text.replace(old, new, 1)


def validate_repository(value: str, host: str) -> str:
    repository = value.strip("/")
    if repository.count("/") != 1 or any(
        part in {"", ".", ".."} for part in repository.split("/")
    ):
        raise SystemExit(f"Invalid {host} repository name: {value!r}")
    return repository


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(
            f"Usage: {sys.argv[0]} <AERA source root> "
            "<github owner/repository> <gitee owner/repository>"
        )

    root = Path(sys.argv[1])
    github_repository = validate_repository(sys.argv[2], "GitHub")
    gitee_repository = validate_repository(sys.argv[3], "Gitee")

    github_release_base = f"https://github.com/{github_repository}/releases"
    gitee_asset_base = f"https://gitee.com/{gitee_repository}/raw"
    gitee_plugin_catalog_base = (
        f"{gitee_asset_base}/aera-16.0/vendor/aera-plugins/"
    )
    gitee_plugin_package_base = gitee_plugin_catalog_base
    github_plugin_base = (
        f"https://raw.githubusercontent.com/{github_repository}/"
        "aera-16.0/vendor/aera-plugins/"
    )

    updater_path = root / "bootable/recovery/aeraui/features/update/update_manager.cpp"
    if not updater_path.is_file():
        raise SystemExit(f"AERA update source not found: {updater_path}")
    updater = updater_path.read_text(encoding="utf-8")
    updater_includes = [
        "#include <array>",
        "#include <cerrno>",
        "#include <fcntl.h>",
        "#include <stdio.h>",
        "#include <unistd.h>",
    ]
    missing_updater_includes = [
        include for include in updater_includes if include not in updater
    ]
    if missing_updater_includes:
        updater = replace_once(
            updater,
            "#include <cstdlib>",
            "#include <cstdlib>\n" + "\n".join(missing_updater_includes),
            "OTA multipart download dependencies",
        )
    updater = replace_once(
        updater,
        "bool DownloadFile(const std::string &url, const std::string &path,\n"
        "                  uint64_t maximum, uint64_t expected_size,\n"
        "                  unsigned progress_start, unsigned progress_end) {",
        "bool DownloadFile(const std::string &url, const std::string &path,\n"
        "                  uint64_t maximum, uint64_t expected_size,\n"
        "                  unsigned progress_start, unsigned progress_end,\n"
        "                  unsigned max_attempts = 2,\n"
        "                  uint64_t timeout_override_ms = 0) {",
        "bounded mirror download retries",
    )
    updater = replace_once(
        updater,
        "for (unsigned attempt = 0; attempt < 2 && !gCancel.load(); ++attempt) {",
        "for (unsigned attempt = 0; attempt < max_attempts && !gCancel.load(); ++attempt) {",
        "bounded mirror download attempts",
    )
    updater = replace_once(
        updater,
        "const uint64_t timeout_ms = maximum <= kMaxCatalog ? 30000 : 900000;",
        "const uint64_t timeout_ms = timeout_override_ms != 0\n"
        "        ? timeout_override_ms\n"
        "        : (maximum <= kMaxCatalog ? 30000 : 900000);",
        "bounded mirror download timeout",
    )

    old_urls = '''constexpr char kStableCatalogUrl[] =
    "https://aera-recovery.com/catalog.json";
constexpr char kNightlyCatalogUrl[] =
    "https://aera-recovery.com/catalog-nightly.json";'''
    new_urls = f'''constexpr char kStableCatalogUrl[] =
    "{gitee_asset_base}/aera-recovery-assets/catalog.json";
constexpr char kNightlyCatalogUrl[] =
    "{gitee_asset_base}/aera-recovery-assets/catalog-nightly.json";
constexpr char kGithubStableCatalogUrl[] =
    "{github_release_base}/latest/download/catalog.json";
constexpr char kGithubNightlyCatalogUrl[] =
    "{github_release_base}/latest/download/catalog-nightly.json";'''
    updater = replace_once(updater, old_urls, new_urls, "OTA catalog URLs")

    old_catalog_url_fn = '''const char *CatalogUrl() {
  return GetChannel() == Channel::kNightly
      ? kNightlyCatalogUrl : kStableCatalogUrl;
}'''
    new_catalog_url_fn = '''const char *CatalogUrl() {
  return GetChannel() == Channel::kNightly
      ? kNightlyCatalogUrl : kStableCatalogUrl;
}

const char *CatalogFallbackUrl() {
  return GetChannel() == Channel::kNightly
      ? kGithubNightlyCatalogUrl : kGithubStableCatalogUrl;
}'''
    updater = replace_once(
        updater, old_catalog_url_fn, new_catalog_url_fn,
        "OTA catalog fallback selector",
    )

    old_parse_release = '''  release->url = value.get("ota_url", "").asString();
  if (release->url.empty()) release->url = value["url"].asString();
  release->changelog.clear();'''
    new_parse_release = '''  release->url = value.get("ota_url", "").asString();
  if (release->url.empty()) release->url = value["url"].asString();
  release->ota_parts.clear();
  const Json::Value &parts = value["ota_parts"];
  if (value.isMember("ota_parts") && !parts.isArray()) return false;
  if (parts.isArray()) {
    if (parts.size() > 32) return false;
    for (Json::ArrayIndex i = 0; i < parts.size(); ++i) {
      DownloadPart part;
      part.url = parts[i].get("url", "").asString();
      part.size = JsonUnsigned(parts[i]["size"]);
      release->ota_parts.push_back(part);
    }
  }
  release->fallback_url = value.get("fallback_url", "").asString();
  release->changelog.clear();'''
    updater = replace_once(
        updater, old_parse_release, new_parse_release,
        "OTA fallback URL parsing",
    )
    updater = replace_once(
        updater,
        "SafeSha256(release->sha256) && SafeHttps(release->url);",
        "SafeSha256(release->sha256) && ValidOtaParts(*release) &&\n"
        "      (release->fallback_url.empty() || SafeHttps(release->fallback_url));",
        "OTA fallback URL validation",
    )

    updater = replace_once(
        updater,
        "bool ParseRelease(const Json::Value &value, Release *release) {",
        '''bool ValidOtaParts(const Release &release) {
  if (release.ota_parts.empty()) return SafeHttps(release.url);
  if (release.ota_parts.size() > 32 || !SafeHttps(release.url)) return false;
  constexpr uint64_t kMaxOtaPart = 20ULL * 1024 * 1024;
  uint64_t total = 0;
  for (const DownloadPart &part : release.ota_parts) {
    if (!SafeHttps(part.url) || part.size == 0 || part.size > kMaxOtaPart ||
        part.size > release.size || total > release.size - part.size)
      return false;
    total += part.size;
  }
  return total == release.size;
}

bool DownloadParts(const Release &release, const std::string &path) {
  if (release.ota_parts.empty()) return false;
  const std::string assembled_path = path + ".assembling";
  unlink(path.c_str());
  unlink(assembled_path.c_str());
  int output = open(assembled_path.c_str(),
                    O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW | O_CLOEXEC,
                    0600);
  if (output < 0) return false;

  uint64_t total = 0;
  bool ok = true;
  std::array<unsigned char, 65536> buffer {};
  for (size_t index = 0; index < release.ota_parts.size(); ++index) {
    if (gCancel.load()) {
      ok = false;
      break;
    }
    const DownloadPart &part = release.ota_parts[index];
    const std::string part_path = path + ".chunk" + std::to_string(index);
    if (!DownloadFile(part.url, part_path, part.size + 1, part.size,
                      0, 90, 1, 60000)) {
      ok = false;
      break;
    }
    const int input = open(part_path.c_str(), O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (input < 0) {
      ok = false;
      break;
    }
    while (ok) {
      const ssize_t count = read(input, buffer.data(), buffer.size());
      if (count < 0 && errno == EINTR) continue;
      if (count < 0) {
        ok = false;
        break;
      }
      if (count == 0) break;
      if (static_cast<uint64_t>(count) > release.size - total) {
        ok = false;
        break;
      }
      size_t offset = 0;
      while (offset < static_cast<size_t>(count)) {
        const ssize_t written = write(
            output, buffer.data() + offset,
            static_cast<size_t>(count) - offset);
        if (written < 0 && errno == EINTR) continue;
        if (written <= 0) {
          ok = false;
          break;
        }
        offset += static_cast<size_t>(written);
      }
      total += static_cast<uint64_t>(count);
      gDownloaded.store(total);
      gTotal.store(release.size);
      gProgress.store(static_cast<unsigned>(total * 90 / release.size));
    }
    close(input);
    unlink(part_path.c_str());
    if (!ok) break;
  }

  if (ok && total == release.size && fsync(output) == 0) {
    if (close(output) != 0) ok = false;
    output = -1;
  } else {
    ok = false;
  }
  if (output >= 0) close(output);
  for (size_t index = 0; index < release.ota_parts.size(); ++index)
    unlink((path + ".chunk" + std::to_string(index)).c_str());
  if (!ok || total != release.size) {
    unlink(assembled_path.c_str());
    unlink(path.c_str());
    return false;
  }
  unlink(path.c_str());
  if (rename(assembled_path.c_str(), path.c_str()) != 0) {
    unlink(assembled_path.c_str());
    return false;
  }
  gDownloaded.store(release.size);
  gProgress.store(90);
  return true;
}

bool ParseRelease(const Json::Value &value, Release *release) {''',
        "OTA multipart download implementation",
    )

    old_catalog_fetch = '''  const char *catalog_url = CatalogUrl();
  if (!DownloadFile(catalog_url, kCatalogPath, kMaxCatalog, 0, 2, 25)) {
    SetPhase(Phase::kError, "Could not reach the update service", false);
    return false;
  }'''
    new_catalog_fetch = '''  const char *catalog_urls[] = {CatalogUrl(), CatalogFallbackUrl()};
  bool catalog_downloaded = false;
  for (const char *catalog_url : catalog_urls) {
    if (DownloadFile(catalog_url, kCatalogPath, kMaxCatalog, 0, 2, 25)) {
      catalog_downloaded = true;
      break;
    }
  }
  if (!catalog_downloaded) {
    SetPhase(Phase::kError, "Could not reach the update service", false);
    return false;
  }'''
    updater = replace_once(
        updater, old_catalog_fetch, new_catalog_fetch,
        "OTA catalog fallback download",
    )

    old_package_fetch = '''  if (!DownloadFile(snapshot.release.url, partial_path, limit,
                    snapshot.release.size, 0, 90)) {
    SetPhase(Phase::kError, "The recovery package could not be downloaded", true);
    return false;
  }'''
    new_package_fetch = '''  bool package_downloaded = snapshot.release.ota_parts.empty()
      ? DownloadFile(snapshot.release.url, partial_path, limit,
                     snapshot.release.size, 0, 90)
      : DownloadParts(snapshot.release, partial_path);
  if (!package_downloaded && !snapshot.release.fallback_url.empty()) {
    unlink(partial_path.c_str());
    package_downloaded = DownloadFile(
        snapshot.release.fallback_url, partial_path, limit,
        snapshot.release.size, 0, 90, 1, 300000);
  }
  if (!package_downloaded) {
    SetPhase(Phase::kError, "The recovery package could not be downloaded", true);
    return false;
  }'''
    updater = replace_once(
        updater, old_package_fetch, new_package_fetch,
        "OTA package fallback download",
    )
    old_package_verify = '''  if (!HashFile(partial_path, snapshot.release.size, snapshot.release.sha256)) {
    unlink(partial_path.c_str());
    SetPhase(Phase::kError,
             "The downloaded package does not match its SHA-256", true);
    return false;
  }'''
    new_package_verify = '''  if (!HashFile(partial_path, snapshot.release.size, snapshot.release.sha256)) {
    unlink(partial_path.c_str());
    bool fallback_verified = false;
    if (!snapshot.release.fallback_url.empty()) {
      SetPhase(Phase::kDownloading,
               "The Gitee package did not verify; trying GitHub", true);
      fallback_verified = DownloadFile(
          snapshot.release.fallback_url, partial_path, limit,
          snapshot.release.size, 0, 90, 1, 300000);
      if (fallback_verified) {
        SetPhase(Phase::kVerifying, "Verifying the downloaded package", true);
        fallback_verified = HashFile(
            partial_path, snapshot.release.size, snapshot.release.sha256);
      }
    }
    if (!fallback_verified) {
      unlink(partial_path.c_str());
      SetPhase(Phase::kError,
               "The downloaded package does not match its SHA-256", true);
      return false;
    }
  }'''
    updater = replace_once(
        updater, old_package_verify, new_package_verify,
        "OTA checksum fallback download",
    )
    updater_path.write_text(updater, encoding="utf-8", newline="\n")

    update_header_path = root / "bootable/recovery/aeraui/features/update/update_manager.hpp"
    if not update_header_path.is_file():
        raise SystemExit(f"AERA update header not found: {update_header_path}")
    update_header = update_header_path.read_text(encoding="utf-8")
    update_header = replace_once(
        update_header,
        "struct Release {\n",
        "struct DownloadPart {\n  std::string url;\n  uint64_t size = 0;\n};\n\n"
        "struct Release {\n  std::vector<DownloadPart> ota_parts;\n",
        "OTA multipart download model",
    )
    update_header = replace_once(
        update_header,
        "  std::string url;\n  std::vector<std::string> changelog;",
        "  std::string url;\n  std::string fallback_url;\n"
        "  std::vector<std::string> changelog;",
        "OTA fallback URL model field",
    )
    update_header_path.write_text(update_header, encoding="utf-8", newline="\n")

    plugin_path = root / "bootable/recovery/aeraui/features/plugins/plugin_manager.cpp"
    if not plugin_path.is_file():
        raise SystemExit(f"AERA plugin source not found: {plugin_path}")
    plugins = plugin_path.read_text(encoding="utf-8")
    plugins = replace_once(
        plugins,
        '"https://raw.githubusercontent.com/AERA-Plugins/registry/main/catalog.json"',
        f'"{gitee_plugin_catalog_base}catalog.json"',
        "plugin catalog URL",
    )
    plugins = replace_once(
        plugins,
        '"https://raw.githubusercontent.com/AERA-Plugins/registry/main/catalog.json.sig"',
        f'"{gitee_plugin_catalog_base}catalog.json.sig"',
        "plugin catalog signature URL",
    )

    old_official_url = '''bool OfficialUrl(const std::string &url) {
  constexpr char raw[] = "https://raw.githubusercontent.com/AERA-Plugins/";
  constexpr char github[] = "https://github.com/AERA-Plugins/";
  return url.compare(0, sizeof(raw) - 1, raw) == 0 ||
         url.compare(0, sizeof(github) - 1, github) == 0;
}'''
    new_url_resolution = f'''constexpr char kGiteePluginMirrorPrefix[] = "{gitee_plugin_package_base}";
constexpr char kGithubPluginMirrorPrefix[] = "{github_plugin_base}";
bool OfficialUrl(const std::string &url) {{
  constexpr char raw[] = "https://raw.githubusercontent.com/AERA-Plugins/";
  constexpr char github[] = "https://github.com/AERA-Plugins/";
  return url.compare(0, sizeof(raw) - 1, raw) == 0 ||
         url.compare(0, sizeof(github) - 1, github) == 0;
}}
std::string PluginAssetName(const std::string &url) {{
  std::array<uint8_t, EVP_MAX_MD_SIZE> digest{{}};
  unsigned int digest_size = 0;
  if (EVP_Digest(url.data(), url.size(), digest.data(), &digest_size,
                 EVP_sha256(), nullptr) != 1 || digest_size != 32)
    return {{}};
  static constexpr char hex[] = "0123456789abcdef";
  std::string name;
  name.reserve(digest_size * 2);
  for (unsigned int index = 0; index < digest_size; ++index) {{
    name.push_back(hex[digest[index] >> 4]);
    name.push_back(hex[digest[index] & 0x0f]);
  }}
  return name;
}}
std::string ResolvePrimaryDownloadUrl(const std::string &url) {{
  if (url.compare(0, sizeof(kGiteePluginMirrorPrefix) - 1,
                  kGiteePluginMirrorPrefix) == 0 ||
      url.compare(0, sizeof(kGithubPluginMirrorPrefix) - 1,
                  kGithubPluginMirrorPrefix) == 0)
    return url;
  if (!OfficialUrl(url)) return {{}};
  const std::string name = PluginAssetName(url);
  return name.empty() ? std::string() :
      std::string(kGiteePluginMirrorPrefix) + name;
}}
std::string ResolveFallbackDownloadUrl(const std::string &url) {{
  if (url.compare(0, sizeof(kGiteePluginMirrorPrefix) - 1,
                  kGiteePluginMirrorPrefix) == 0)
    return std::string(kGithubPluginMirrorPrefix) +
        url.substr(sizeof(kGiteePluginMirrorPrefix) - 1);
  if (url.compare(0, sizeof(kGithubPluginMirrorPrefix) - 1,
                  kGithubPluginMirrorPrefix) == 0 || !OfficialUrl(url))
    return {{}};
  const std::string name = PluginAssetName(url);
  return name.empty() ? std::string() :
      std::string(kGithubPluginMirrorPrefix) + name;
}}'''
    plugins = replace_once(
        plugins, old_official_url, new_url_resolution,
        "official plugin URL policy and dual mirror resolver",
    )

    old_download_guard = '''  if (!OfficialUrl(url) || limit == 0 || limit > kMaxPayload) return false;
  for (unsigned attempt = 0; attempt < 3; ++attempt) {'''
    new_download_guard = '''  const std::string download_url = ResolvePrimaryDownloadUrl(url);
  const std::string fallback_url = ResolveFallbackDownloadUrl(url);
  if (download_url.empty() || limit == 0 || limit > kMaxPayload) return false;
  for (unsigned attempt = 0; attempt < 6; ++attempt) {
    if (attempt >= 3 && fallback_url.empty()) break;
    const std::string &current_url = attempt < 3 ? download_url : fallback_url;'''
    plugins = replace_once(
        plugins, old_download_guard, new_download_guard,
        "plugin download URL resolution",
    )
    plugins = replace_once(
        plugins,
        '"-O", path.c_str(), url.c_str(), nullptr};',
        '"-O", path.c_str(), current_url.c_str(), nullptr};',
        "plugin mirror download target",
    )
    plugin_path.write_text(plugins, encoding="utf-8", newline="\n")

    print(
        "AERA OTA downloads use the repository mirrors; signed plugin "
        "catalogs and packages use Gitee source files first, with GitHub "
        f"Raw fallback ({gitee_repository}; {github_repository})."
    )


if __name__ == "__main__":
    main()
