// AERA endpoint recovery with header probes.
// Network work stays outside LVGL and outside the signed WebKit runtime.
// A public HTTPS probe verifies a DNS candidate before a temporary hosts entry
// is used. Restarting the isolated worker discards its failed DNS/connection
// cache; cookies and the verified on-disk engine stay in their existing paths.
bool BrowserNetworkError(std::string error) {
  for (char &c : error) if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
  if (error.find("certificat") != std::string::npos ||
      error.find("cancel") != std::string::npos) return false;
  for (const char *word : {"connect", "resolve", "timeout", "timed out", "network",
                           "socket", "connection reset", "connection closed"})
    if (error.find(word) != std::string::npos) return true;
  return false;
}

bool BrowserNetworkTick(WebScene *s, bool visible) {
  const uint64_t now = aera_network::NowMs();
  if (s->network_hosts_active && now >= s->network_refresh) {
    aera_network::BrowserHosts(s->state.directory);
    s->network_refresh = now + 5000;
  }
  if (s->network_worker.joinable() && s->network_done.load(std::memory_order_acquire)) {
    s->network_worker.join();
    s->network_working = false;
    s->network_restart = !s->network_winner.empty() &&
        s->session.LastUrl() == s->network_url && !s->network_cancel.load();
  }
  if (s->session.LastUrl() != s->network_url ||
      s->session.NavigationStopped() ||
      (s->session.Progress() == 100 && s->session.LastError().empty())) {
    s->network_cancel.store(true);
    s->network_restart = false;
  }
  if (s->network_restart && visible && s->session.Connected() &&
      web::CurrentDownloadSummary().active_count == 0) {
    s->network_restart = false;
    const std::string host = aera_network::GithubHost(s->network_url);
    if (s->session.LastUrl() != s->network_url || s->session.NavigationStopped() ||
        aera_network::Cached(host).ip != s->network_winner) return false;
    if (s->frame_waiting_for_refresh) s->session.AcknowledgeFrame();
    s->frame_waiting_for_refresh = false;
    ResetBrowserTouches(s);
    lv_image_set_src(s->image, nullptr);
    lv_image_cache_drop(&s->descriptor);
    // The immutable LVGL image header is reused by the replacement session.
    s->descriptor.data = nullptr;
    s->showing_web = false;
    lv_obj_add_flag(s->viewport, LV_OBJ_FLAG_HIDDEN);
    s->session.Send(web::Kind::kClose);
    s->process.Stop();
    s->session.Close();
    s->network_hosts_active = aera_network::BrowserHosts(s->state.directory);
    s->network_refresh = now + 5000;
    fprintf(stderr, "AERA browser network: rebuilding session for %s through %s\n",
            host.c_str(), s->network_winner.c_str());
    s->restart_url = s->network_url;
    s->session_was_started = false;
    s->finished = false;
    return true;
  }
  if (!s->session.Connected() || s->session.NavigationStopped()) {
    s->network_cancel.store(true);
    return false;
  }
  const auto &url = s->session.LastUrl();
  const std::string host = aera_network::GithubHost(url);
  if (s->network_working && url != s->network_url) s->network_cancel.store(true);
  if (s->network_observed_url != url || s->network_progress != s->session.Progress()) {
    s->network_observed_url = url;
    s->network_progress = s->session.Progress();
    s->network_progress_at = now;
  }
  const bool error = s->network_error_seen != s->session.ErrorRevision() &&
      BrowserNetworkError(s->session.LastError());
  const bool stalled = s->session.Progress() < 100 &&
      now - s->network_progress_at >= 20000;
  if (!visible || host.empty() || s->network_working || s->network_restart ||
      s->network_attempted.count(url) || s->network_attempted.size() >= 8 ||
      web::CurrentDownloadSummary().active_count != 0 || (!error && !stalled)) return false;
  s->network_error_seen = s->session.ErrorRevision();
  s->network_attempted.insert(url);
  s->network_url = url;
  s->network_winner.clear();
  s->network_working = true;
  s->network_cancel.store(false);
  s->network_done.store(false, std::memory_order_relaxed);
  fprintf(stderr, "AERA browser network: recovery requested for %s reason=%s progress=%u\n",
          host.c_str(), error ? "network-error" : "stalled", s->session.Progress());
  const std::string runtime = s->state.directory;
  s->network_worker = std::thread([s, url, host, runtime] {
    const auto cancelled = [s] {
      return s->network_cancel.load() || s->state.cancel.load();
    };
    const auto old = aera_network::Cached(host);
    aera_network::Forget(host);
    const std::string probe = runtime + "/.network-probe";
    // Probe only the public origin, excluding paths, tokens and cookies.
    const std::string public_url = "https://" + host + "/";
    const auto primary = aera_network::PrimaryAddresses(
        url, runtime + "/etc/resolv.conf", cancelled);
    const auto candidates = aera_network::Candidates(url, cancelled);
    const auto primary_address = [&primary](const aera_network::Address &candidate) {
      return std::any_of(primary.begin(), primary.end(), [&](const auto &entry) {
        return entry.ip == candidate.ip;
      });
    };
    const bool has_alternate = std::any_of(candidates.begin(), candidates.end(),
        [&](const auto &candidate) { return !primary_address(candidate); });
    unsigned attempts = 0;
    for (const auto &candidate : candidates) {
      if (cancelled() || attempts >= 3) break;
      if (candidate.ip == old.ip || (has_alternate && primary_address(candidate))) continue;
      ++attempts;
      fprintf(stderr, "AERA browser network: probing public origin %s endpoint %s\n",
              host.c_str(), candidate.ip.c_str());
      // A slow home-page body must not discard a TLS-verified alternate route.
      // Only this origin probe uses HEAD; signed payloads still use full GET.
      if (aera_https::Download(public_url, probe, 2 * 1024 * 1024, 0,
              [](uint64_t) {}, cancelled, 1, 8000, host, candidate, false, true) &&
          aera_network::Cached(host).ip == candidate.ip && !cancelled()) {
        s->network_winner = candidate.ip;
        fprintf(stderr, "AERA browser network: verified alternate endpoint for %s through %s\n",
                host.c_str(), candidate.ip.c_str());
        break;
      }
    }
    unlink(probe.c_str());
    unlink((probe + ".download.log").c_str());
    s->network_done.store(true, std::memory_order_release);
  });
  return false;
}
