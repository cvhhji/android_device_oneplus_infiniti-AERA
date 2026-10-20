#!/usr/bin/env python3
"""Expose the recovery's existing multilingual fonts read-only to WebKit."""

from pathlib import Path
import sys


def once(text: str, anchor: str, replacement: str) -> str:
    if text.count(anchor) != 1:
        raise SystemExit("Browser font integration anchor changed; review before applying")
    return text.replace(anchor, replacement, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <AERA source root>")
    source = Path(sys.argv[1]) / "bootable/recovery/aeraui/features/browser/jail_main.cpp"
    text = source.read_text(encoding="utf-8")
    scene = source.with_name("web_scene.cpp")
    ui = scene.read_text(encoding="utf-8")
    if "static void PrepareBrowserFontMount(int root)" in text:
        if "bool session_was_started = false;" in ui:
            print("AERA browser already has multilingual fonts and bounded session recovery.")
            return
        raise SystemExit("Browser integration is partially applied; review before continuing")
    function = '''// Fonts are data from the recovery ramdisk, separate from the signed plugin.
// Keep the runtime's original fonts and add only this narrow read-only view.
static void PrepareBrowserFontMount(int root) {
  int source = open("/twres/fonts", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  struct stat info{};
  if (source < 0 || fstat(source, &info) || info.st_uid || (info.st_mode & 0022))
    Die("trusted recovery font directory");
  close(source);
  int parent = dup(root);
  if (parent < 0) Die("browser font mount root");
  for (const char *name : {"usr", "share", "fonts"}) {
    int child = openat(parent, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    close(parent);
    if (child < 0 || fstat(child, &info) || info.st_uid || (info.st_mode & 0022))
      Die("safe browser font directory");
    parent = child;
  }
  if (mkdirat(parent, "recovery", 0755) && errno != EEXIST)
    Die("browser recovery font mount point");
  int mountpoint = openat(parent, "recovery",
      O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  close(parent);
  if (mountpoint < 0 || fstat(mountpoint, &info) || info.st_uid ||
      (info.st_mode & 0022)) Die("safe recovery font mount point");
  close(mountpoint);
}
'''
    text = once(text, "static void WriteResolverConfig(int root) {",
                function + "static void WriteResolverConfig(int root) {")
    text = once(text, '  if (!retroarch && !doom && !media && !recorder && !streams_media)\n'
                '    WriteResolverConfig(directory);',
                '  if (browser) PrepareBrowserFontMount(directory);\n'
                '  if (!retroarch && !doom && !media && !recorder && !streams_media)\n'
                '    WriteResolverConfig(directory);')
    anchor = '  Check(minijail_bind(jail, root.c_str(), "/", 0), "read-only runtime");'
    text = once(text, anchor, anchor + '''
  if (browser)
    Check(minijail_bind(jail, "/twres/fonts", "/usr/share/fonts/recovery", 0),
          "read-only multilingual recovery fonts");''')
    text = once(text,
                '  const char *keys[] = {"net.wlan0.dns1", "net.wlan0.dns2", "net.dns1", "net.dns2"};',
                '  const char *keys[] = {"net.wlan0.dns1", "net.wlan0.dns2",\n'
                '                        "net.dns1", "net.dns2", "net.dns3", "net.dns4"};')
    ui = once(ui, "  bool persistent = false;", '''  bool persistent = false;
  bool session_was_started = false;
  unsigned restart_attempts = 0;
  std::string restart_url;''')
    old = '''    if (!s->process.Running() && s->session.Connected())
      s->session.Close();'''
    new = '''    const bool running = s->process.Running();
    if (!running && s->session.Connected())
      s->session.Close();
    // Permit one recovery of an established session, even if Poll() observed
    // EOF before waitpid saw the worker exit. Never loop on startup failure.
    if (!running && s->session_was_started && s->restart_attempts == 0 &&
        s->state.verified && !s->state.directory.empty()) {
      s->restart_url = web::Address(s->last_status);
      ++s->restart_attempts;
      s->finished = false;
    }'''
    ui = once(ui, old, new)
    ui = once(ui, "    const int zoom = RecoveryBrowserZoom();",
              "    s->session_was_started = true;\n    const int zoom = RecoveryBrowserZoom();")
    ui = once(ui, "\n    const auto homepage = web::Address(RecoveryBrowserHomepage());",
              "\n    const auto homepage = s->restart_url.empty()\n"
              "        ? web::Address(RecoveryBrowserHomepage()) : s->restart_url;\n"
              "    s->restart_url.clear();")
    source.write_text(text, encoding="utf-8", newline="\n")
    scene.write_text(ui, encoding="utf-8", newline="\n")
    print("AERA WebKit keeps its signed runtime and gains read-only recovery fonts.")


if __name__ == "__main__":
    main()
