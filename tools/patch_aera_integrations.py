#!/usr/bin/env python3
"""Point AERA OTA and signed plugin downloads at the owner's Gitee mirror.

The Gitee releases are the primary endpoints for mainland networks. GitHub
remains the fallback so the same image continues to work where Gitee is slow
or unavailable.
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
    gitee_release_base = f"https://gitee.com/{gitee_repository}/releases"
    plugin_tag = "aera-plugins-mirror"
    gitee_plugin_base = f"{gitee_release_base}/download/{plugin_tag}/"
    github_plugin_base = f"{github_release_base}/download/{plugin_tag}/"

    updater_path = root / "bootable/recovery/aeraui/features/update/update_manager.cpp"
    if not updater_path.is_file():
        raise SystemExit(f"AERA update source not found: {updater_path}")
    updater = updater_path.read_text(encoding="utf-8")

    old_urls = '''constexpr char kStableCatalogUrl[] =
    "https://aera-recovery.com/catalog.json";
constexpr char kNightlyCatalogUrl[] =
    "https://aera-recovery.com/catalog-nightly.json";'''
    new_urls = f'''constexpr char kStableCatalogUrl[] =
    "{gitee_release_base}/download/aera-latest/catalog.json";
constexpr char kNightlyCatalogUrl[] =
    "{gitee_release_base}/download/aera-latest/catalog-nightly.json";
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
  release->fallback_url = value.get("fallback_url", "").asString();
  release->changelog.clear();'''
    updater = replace_once(
        updater, old_parse_release, new_parse_release,
        "OTA fallback URL parsing",
    )
    updater = replace_once(
        updater,
        "SafeSha256(release->sha256) && SafeHttps(release->url);",
        "SafeSha256(release->sha256) && SafeHttps(release->url) &&\n"
        "      (release->fallback_url.empty() || SafeHttps(release->fallback_url));",
        "OTA fallback URL validation",
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
    new_package_fetch = '''  bool package_downloaded = DownloadFile(
      snapshot.release.url, partial_path, limit, snapshot.release.size, 0, 90);
  if (!package_downloaded && !snapshot.release.fallback_url.empty()) {
    package_downloaded = DownloadFile(
        snapshot.release.fallback_url, partial_path, limit,
        snapshot.release.size, 0, 90);
  }
  if (!package_downloaded) {
    SetPhase(Phase::kError, "The recovery package could not be downloaded", true);
    return false;
  }'''
    updater = replace_once(
        updater, old_package_fetch, new_package_fetch,
        "OTA package fallback download",
    )
    updater_path.write_text(updater, encoding="utf-8", newline="\n")

    update_header_path = root / "bootable/recovery/aeraui/features/update/update_manager.hpp"
    if not update_header_path.is_file():
        raise SystemExit(f"AERA update header not found: {update_header_path}")
    update_header = update_header_path.read_text(encoding="utf-8")
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
        f'"{gitee_plugin_base}catalog.json"',
        "plugin catalog URL",
    )
    plugins = replace_once(
        plugins,
        '"https://raw.githubusercontent.com/AERA-Plugins/registry/main/catalog.json.sig"',
        f'"{gitee_plugin_base}catalog.json.sig"',
        "plugin catalog signature URL",
    )

    old_official_url = '''bool OfficialUrl(const std::string &url) {
  constexpr char raw[] = "https://raw.githubusercontent.com/AERA-Plugins/";
  constexpr char github[] = "https://github.com/AERA-Plugins/";
  return url.compare(0, sizeof(raw) - 1, raw) == 0 ||
         url.compare(0, sizeof(github) - 1, github) == 0;
}'''
    new_url_resolution = f'''constexpr char kGiteePluginMirrorPrefix[] = "{gitee_plugin_base}";
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
        "AERA OTA and signed plugin downloads now use Gitee first, with "
        f"GitHub fallback ({gitee_repository}; {github_repository})."
    )


if __name__ == "__main__":
    main()
