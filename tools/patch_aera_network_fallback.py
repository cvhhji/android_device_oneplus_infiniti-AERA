#!/usr/bin/env python3
"""Connect bounded GitHub endpoint recovery to the native browser bridge."""
from pathlib import Path
import sys


def once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise SystemExit('Network integration anchor changed: ' + old[:80])
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f'Usage: {sys.argv[0]} <AERA source root>')
    root = Path(sys.argv[1]) / 'bootable/recovery/aeraui/features/browser'
    scene = root / 'web_scene.cpp'
    header = root / 'session.hpp'
    source = root / 'session.cpp'
    ui = scene.read_text(encoding='utf-8')
    declarations = header.read_text(encoding='utf-8')
    session = source.read_text(encoding='utf-8')
    if '// AERA bounded GitHub endpoint recovery' in ui:
        if 'const std::string &LastUrl()' not in declarations:
            raise SystemExit('Partially applied browser network fallback')
        print('Browser GitHub endpoint fallback already applied.')
        return
    ui = '#include "../../aera_https_download.hpp"\n#include <atomic>\n' + ui
    ui = once(ui, '  std::thread worker;', '''  std::thread worker;
  // AERA bounded GitHub endpoint recovery
  std::thread network_worker;
  std::atomic<bool> network_done{false}, network_cancel{false};
  bool network_working = false, network_restart = false, network_hosts_active = false;
  std::string network_url, network_winner, network_observed_url;
  std::unordered_set<std::string> network_attempted;
  uint32_t network_error_seen = 0;
  unsigned network_progress = 101;
  uint64_t network_progress_at = 0, network_refresh = 0;''')
    ui = once(ui, '    state.cancel.store(true);', '''    state.cancel.store(true);
    network_cancel.store(true);
    if (network_worker.joinable()) network_worker.join();''')
    ui = once(ui, '  s->state.cancel.store(true);', '''  s->state.cancel.store(true);
  s->network_cancel.store(true);
  if (s->network_worker.joinable()) s->network_worker.join();''')
    helpers = Path(__file__).with_name('aera_browser_network.inc').read_text(encoding='utf-8')
    ui = once(ui, 'void DetachWebScene(WebScene *s) {', helpers + '\nvoid DetachWebScene(WebScene *s) {')
    ui = once(ui, '      const bool new_frame = s->session.Poll();',
              '      const bool new_frame = s->session.Poll();\n'
              '      if (BrowserNetworkTick(s, visible)) return;')
    ui = once(ui, '    if (!s->process.Start(s->state.directory, frame, control, error) ||',
              '    // Drop references before Adopt unmaps the previous shared pixels.\n'
              '    if (s->image) lv_image_set_src(s->image, nullptr);\n'
              '    lv_image_cache_drop(&s->descriptor);\n'
              '    s->descriptor.data = nullptr;\n'
              '    s->frame_waiting_for_refresh = false;\n'
              '    s->network_hosts_active = aera_network::BrowserHosts(s->state.directory, true);\n'
              '    s->network_refresh = aera_network::NowMs() + 5000;\n'
              '    if (!s->process.Start(s->state.directory, frame, control, error) ||')
    declarations = once(declarations, '  const std::string &Status() const { return status_; }',
        '''  const std::string &Status() const { return status_; }
  const std::string &LastUrl() const { return last_url_; }
  const std::string &LastError() const { return last_error_; }
  uint32_t ErrorRevision() const { return error_revision_; }
  bool NavigationStopped() const { return navigation_stopped_; }''')
    declarations = once(declarations, '  std::string status_;', '''  std::string status_;
  std::string last_url_, last_error_;
  uint32_t error_revision_ = 0;
  bool navigation_stopped_ = false;''')
    session = once(session, '  frame_pending_ = false;\n  downloads_.clear();',
        '''  frame_pending_ = false;
  last_url_.clear(); last_error_.clear(); error_revision_ = 0;
  navigation_stopped_ = false;
  downloads_.clear();''')
    session = once(session, '  if (!Valid(message, false)) return false;\n  return Write(message);',
        '''  if (!Valid(message, false) || !Write(message)) return false;
  if (kind == Kind::kStop) navigation_stopped_ = true;
  if (kind == Kind::kOpen || kind == Kind::kReload || kind == Kind::kBack || kind == Kind::kForward) {
    navigation_stopped_ = false;
    last_error_.clear();
    progress_ = 0;
    if (kind == Kind::kOpen && text) last_url_ = Address(text);
  }
  return true;''')
    session = once(session, '      status_ = message.text;\n    } else if (message.kind == Kind::kKeyboardShow)',
        '''      status_ = message.text;
      const auto url = Address(status_);
      if (!url.empty() && url != last_url_) {
        last_url_ = url;
        last_error_.clear();
        navigation_stopped_ = false;
      }
    } else if (message.kind == Kind::kError) {
      status_ = message.text;
      last_error_ = message.text;
      ++error_revision_;
    } else if (message.kind == Kind::kKeyboardShow)''')
    for path, text in ((scene, ui), (header, declarations), (source, session)):
        path.write_text(text, encoding='utf-8', newline='\n')
    print('AERA browser automatically retries GitHub network failures with verified DNS candidates.')


if __name__ == '__main__':
    main()
