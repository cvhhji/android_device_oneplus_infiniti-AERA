#!/usr/bin/env python3
"""Use the recovery's verified HTTPS transport for the upstream font library."""

from pathlib import Path
import sys


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <AERA source root>")
    path = Path(sys.argv[1]) / "bootable/recovery/aeraui/features/fonts/fontsource_download.cpp"
    text = path.read_text(encoding="utf-8")
    marker = "// AERA Fontsource uses verified curl and isolated temporary files."
    if marker in text:
        print("AERA font library already uses verified HTTPS.")
        return
    start = text.find("  int output[2];")
    end = text.find("\n  return true;\n}", start)
    if start < 0 or end < 0 or 'executable, "wget"' not in text[start:end]:
        raise SystemExit("Upstream font downloader changed; review before applying")
    # Leave the upstream metadata / font URL allowlist intact. Only replace
    # transport and collection; JSON, size and FreeType validation still run.
    replacement = '''  // AERA Fontsource uses verified curl and isolated temporary files.
  char directory[] = "/tmp/aera-font-XXXXXX";
  if (!mkdtemp(directory)) { error = "Download failed"; return false; }
  struct TemporaryDownload {
    std::string directory, path;
    ~TemporaryDownload() {
      unlink(path.c_str());
      unlink((path + ".download.log").c_str());
      rmdir(directory.c_str());
    }
  } temporary{directory, std::string(directory) + "/payload"};
  if (!aera_https::Download(url, temporary.path, limit, 0,
          [](uint64_t) {}, [&cancel] { return cancel.load(); }, 2, 45000)) {
    error = "Download failed"; return false;
  }
  struct stat info{};
  if (lstat(temporary.path.c_str(), &info) || !S_ISREG(info.st_mode) ||
      info.st_size <= 0 || static_cast<uint64_t>(info.st_size) > limit) {
    error = "Download failed"; return false;
  }
  std::ifstream input(temporary.path, std::ios::binary);
  bytes.assign(std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>());
  if (input.bad() || bytes.size() != static_cast<size_t>(info.st_size) || cancel.load()) {
    bytes.clear(); error = "Download failed"; return false;
  }'''
    text = ('#include "../../aera_https_download.hpp"\n'
            '#include <cstdlib>\n#include <fstream>\n#include <iterator>\n' + text)
    # Include insertion changes offsets, so locate the preserved anchors again.
    start = text.index("  int output[2];")
    end = text.index("\n  return true;\n}", start)
    text = text[:start] + replacement + text[end:]
    path.write_text(text, encoding="utf-8", newline="\n")
    print("AERA font library retains its URL validation and uses verified curl.")


if __name__ == "__main__":
    main()
