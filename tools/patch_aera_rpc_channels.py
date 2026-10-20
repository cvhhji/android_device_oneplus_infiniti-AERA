#!/usr/bin/env python3
"""Serialize RPC channel access and reuse validated FIFO nodes across requests."""

from pathlib import Path
import sys


def once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise SystemExit("AERA RPC channel code changed; review before applying")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <AERA source root>")
    path = Path(sys.argv[1]) / "bootable/recovery/aera_rpc/aera_channel.cpp"
    text = path.read_text(encoding="utf-8")
    if "std::recursive_mutex g_channel_lock;" in text:
        print("AERA RPC already serializes and recovers its FIFO channels.")
        return
    text = once(text, "#include <fcntl.h>\n", "#include <fcntl.h>\n#include <mutex>\n")
    text = once(text, "std::string g_pending;\n", '''std::string g_pending;
// UI polling and dispatcher completion run on different threads.
std::recursive_mutex g_channel_lock;
bool g_channels_enabled = false;

bool EnsureFifo(const char *path, mode_t mode) {
  if (mkfifo(path, mode) != 0 && errno != EEXIST) return false;
  struct stat info{};
  if (lstat(path, &info) != 0) return false;
  if (!S_ISFIFO(info.st_mode) || info.st_uid != 0) {
    errno = EPERM;
    return false;
  }
  return true;
}
''')
    text = once(text, '''  unlink(AERA_RPC_INPUT_FILE);
  unlink(AERA_RPC_OUTPUT_FILE);
  if (mkfifo(AERA_RPC_INPUT_FILE, 0660) != 0 ||
      mkfifo(AERA_RPC_OUTPUT_FILE, 0666) != 0) {''', '''  // Reusing the same validated nodes also keeps a just-opened client from
  // holding an output FIFO that the server has already unlinked.
  if (!EnsureFifo(AERA_RPC_INPUT_FILE, 0660) ||
      !EnsureFifo(AERA_RPC_OUTPUT_FILE, 0666)) {''')
    text = once(text, '''  unlink(AERA_RPC_CANCEL_FILE);
  if (mkfifo(AERA_RPC_CANCEL_FILE, 0660) != 0) {''',
                '''  if (!EnsureFifo(AERA_RPC_CANCEL_FILE, 0660)) {''')
    for declaration in ("void Channel::Setup() {", "void Channel::Shutdown() {",
                        "void Channel::Rearm() {", "void Channel::HandleInput() {",
                        "bool Channel::HandleCancel() {"):
        text = once(text, declaration,
                    declaration + "\n  std::lock_guard<std::recursive_mutex> guard(g_channel_lock);")
    text = once(text, '''void Channel::Setup() {
  std::lock_guard<std::recursive_mutex> guard(g_channel_lock);''', '''void Channel::Setup() {
  std::lock_guard<std::recursive_mutex> guard(g_channel_lock);
  g_channels_enabled = true;''')
    text = once(text, '''void Channel::Shutdown() {
  std::lock_guard<std::recursive_mutex> guard(g_channel_lock);''', '''void Channel::Shutdown() {
  std::lock_guard<std::recursive_mutex> guard(g_channel_lock);
  g_channels_enabled = false;''')
    text = once(text, '''void Channel::Rearm() {
  std::lock_guard<std::recursive_mutex> guard(g_channel_lock);
  g_pending.clear();
  OpenInput();
}''', '''void Channel::Rearm() {
  std::lock_guard<std::recursive_mutex> guard(g_channel_lock);
  g_pending.clear();
  if (g_channels_enabled && g_input < 0) OpenInput();
}''')
    text = once(text, "int Channel::InputFd() { return g_input; }", '''int Channel::InputFd() {
  std::lock_guard<std::recursive_mutex> guard(g_channel_lock);
  // Recover a failed open during normal UI polling, after any job has ended.
  if (g_channels_enabled && g_input < 0 && !Dispatcher::Active()) OpenInput();
  return g_input;
}''')
    text = once(text, "int Channel::CancelFd() { return g_cancel; }", '''int Channel::CancelFd() {
  std::lock_guard<std::recursive_mutex> guard(g_channel_lock);
  return g_cancel;
}''')
    path.write_text(text, encoding="utf-8", newline="\n")
    print("AERA RPC serializes FIFO state, validates existing nodes, and recovers a missing reader.")


if __name__ == "__main__":
    main()
