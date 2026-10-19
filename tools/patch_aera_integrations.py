#!/usr/bin/env python3
"""Point AERA update and plugin downloads at this device-tree owner's releases."""

from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0 and new in text:
        return text
    if count != 1:
        raise SystemExit(f"Expected one source match for {label}; found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(
            f"Usage: {sys.argv[0]} <AERA source root> <owner/repository>"
        )

    root = Path(sys.argv[1])
    repository = sys.argv[2].strip("/")
    if repository.count("/") != 1 or any(part in {"", ".", ".."} for part in repository.split("/")):
        raise SystemExit(f"Invalid GitHub repository name: {repository!r}")

    release_base = f"https://github.com/{repository}/releases"
    updater_path = root / "bootable/recovery/aeraui/features/update/update_manager.cpp"
    if not updater_path.is_file():
        raise SystemExit(f"AERA update source not found: {updater_path}")
    updater = updater_path.read_text(encoding="utf-8")
    updater = replace_once(
        updater,
        '"https://aera-recovery.com/catalog.json"',
        f'"{release_base}/latest/download/catalog.json"',
        "stable update catalog URL",
    )
    updater = replace_once(
        updater,
        '"https://aera-recovery.com/catalog-nightly.json"',
        f'"{release_base}/latest/download/catalog-nightly.json"',
        "nightly update catalog URL",
    )
    updater_path.write_text(updater, encoding="utf-8", newline="\n")

    plugin_path = root / "bootable/recovery/aeraui/features/plugins/plugin_manager.cpp"
    if not plugin_path.is_file():
        raise SystemExit(f"AERA plugin source not found: {plugin_path}")
    plugins = plugin_path.read_text(encoding="utf-8")
    mirror_tag = "aera-plugins-mirror"
    mirror_base = f"{release_base}/download/{mirror_tag}/"
    plugins = replace_once(
        plugins,
        '"https://raw.githubusercontent.com/AERA-Plugins/registry/main/catalog.json"',
        f'"{mirror_base}catalog.json"',
        "plugin catalog URL",
    )
    plugins = replace_once(
        plugins,
        '"https://raw.githubusercontent.com/AERA-Plugins/registry/main/catalog.json.sig"',
        f'"{mirror_base}catalog.json.sig"',
        "plugin catalog signature URL",
    )

    old_official_url = '''bool OfficialUrl(const std::string &url) {
  constexpr char raw[] = "https://raw.githubusercontent.com/AERA-Plugins/";
  constexpr char github[] = "https://github.com/AERA-Plugins/";
  return url.compare(0, sizeof(raw) - 1, raw) == 0 ||
         url.compare(0, sizeof(github) - 1, github) == 0;
}'''
    new_official_url = f'''constexpr char kPluginMirrorPrefix[] = "{mirror_base}";
bool OfficialUrl(const std::string &url) {{
  constexpr char raw[] = "https://raw.githubusercontent.com/AERA-Plugins/";
  constexpr char github[] = "https://github.com/AERA-Plugins/";
  return url.compare(0, sizeof(raw) - 1, raw) == 0 ||
         url.compare(0, sizeof(github) - 1, github) == 0;
}}
bool IsPluginMirrorUrl(const std::string &url) {{
  return url.compare(0, sizeof(kPluginMirrorPrefix) - 1,
                     kPluginMirrorPrefix) == 0;
}}
std::string ResolveDownloadUrl(const std::string &url) {{
  if (IsPluginMirrorUrl(url)) return url;
  if (!OfficialUrl(url)) return {{}};
  std::array<uint8_t, EVP_MAX_MD_SIZE> digest{{}};
  unsigned int digest_size = 0;
  if (EVP_Digest(url.data(), url.size(), digest.data(), &digest_size,
                 EVP_sha256(), nullptr) != 1 || digest_size != 32)
    return {{}};
  static constexpr char hex[] = "0123456789abcdef";
  std::string resolved(kPluginMirrorPrefix);
  resolved.reserve(resolved.size() + digest_size * 2);
  for (unsigned int index = 0; index < digest_size; ++index) {{
    resolved.push_back(hex[digest[index] >> 4]);
    resolved.push_back(hex[digest[index] & 0x0f]);
  }}
  return resolved;
}}'''
    plugins = replace_once(plugins, old_official_url, new_official_url, "official plugin URL policy")

    old_download_guard = '''  if (!OfficialUrl(url) || limit == 0 || limit > kMaxPayload) return false;
  for (unsigned attempt = 0; attempt < 3; ++attempt) {'''
    new_download_guard = '''  const std::string download_url = ResolveDownloadUrl(url);
  if (download_url.empty() || limit == 0 || limit > kMaxPayload) return false;
  for (unsigned attempt = 0; attempt < 3; ++attempt) {'''
    plugins = replace_once(plugins, old_download_guard, new_download_guard, "plugin download URL resolution")
    plugins = replace_once(
        plugins,
        '"-O", path.c_str(), url.c_str(), nullptr};',
        '"-O", path.c_str(), download_url.c_str(), nullptr};',
        "plugin mirror download target",
    )
    plugin_path.write_text(plugins, encoding="utf-8", newline="\n")

    print(f"AERA OTA catalogs and signed plugin mirror now use {repository}.")


if __name__ == "__main__":
    main()
