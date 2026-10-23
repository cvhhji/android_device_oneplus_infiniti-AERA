#!/usr/bin/env python3
"""Add recovery-scoped NR preference controls to the pinned native mobile UI."""
from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str) -> str:
    if new in text:
        return text
    if text.count(old) != 1:
        raise SystemExit("Radio-mode integration anchor changed; review before applying")
    return text.replace(old, new, 1)


MODE_API = '''int RecoveryMobileRadioMode() {
  LoadAeraPreferencesIfAvailable();
  return std::clamp(DataManager::GetIntValue("aera_mobile_radio_mode"), 0, 1);
}
bool RecoverySetMobileRadioMode(int mode, std::string *error) {
  if (!MobileDataEnabled() || mode < 0 || mode > 1) return false;
  if (RecoveryDataLocked()) {
    if (error) *error = "Unlock internal storage before saving mobile data settings";
    return false;
  }
  if (RecoveryMobileStatus().enabled || RecoveryMobileSimSwitching()) {
    if (error) *error = "Turn off mobile data before changing network mode";
    return false;
  }
  const int previous = RecoveryMobileRadioMode();
  DataManager::SetValue("aera_mobile_radio_mode", mode);
  if (SaveAeraPreferences()) return true;
  DataManager::SetValue("aera_mobile_radio_mode", previous);
  if (error) *error = "Could not save mobile data settings";
  return false;
}
'''

MODE_REFRESH = '''  for(size_t i=0;i<state->mode.size();++i) {
    const bool active=state->radio_mode==static_cast<int>(i);
    lv_obj_set_style_border_width(state->mode[i],active?3:SurfaceStyleValue()==2?2:1,0);
    lv_obj_set_style_border_color(state->mode[i],active?kAccent:kMainLine,0);
    lv_obj_set_style_border_opa(state->mode[i],active?LV_OPA_COVER:LV_OPA_50,0);
    if(mobile.enabled||RecoveryMobileSimSwitching())lv_obj_add_state(state->mode[i],LV_STATE_DISABLED);
    else lv_obj_remove_state(state->mode[i],LV_STATE_DISABLED);
  }
  i18n::BindLabel(state->mode_detail,mobile.enabled?
      "Turn off mobile data to change mode. 5G only may lose service":state->radio_mode==1?
      "No 4G fallback. Standalone 5G coverage is required":
      "Prefer 5G and allow 4G fallback. Applies only in recovery");
'''

MODE_CARD = '''  auto *mode_card=card(configuration);
  label(mode_card,"Network mode",&lv_font_montserrat_24,kMuted);
  auto *mode_choices=lv_obj_create(mode_card);Clear(mode_choices);
  lv_obj_set_size(mode_choices,LV_PCT(100),110);
  lv_obj_set_flex_flow(mode_choices,LV_FLEX_FLOW_ROW);
  lv_obj_set_style_pad_column(mode_choices,16,0);
  const std::array<const char *,2> mode_names{"5G preferred","5G only"};
  for(int i=0;i<2;++i) {
    state->mode[i]=Button(mode_choices,mode_names[i],[state,i]{
      if(state->radio_mode==i)return;
      state->error.clear();
      if(RecoverySetMobileRadioMode(i,&state->error))state->radio_mode=i;
      RefreshMobile(state);
    });
    Panel(state->mode[i],30,kMainPanel);
    lv_obj_set_flex_grow(state->mode[i],1);lv_obj_set_width(state->mode[i],0);
    lv_obj_set_height(state->mode[i],104);
  }
  state->mode_detail=label(mode_card,"",&lv_font_montserrat_24,kMuted);
'''


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <AERA source root>")
    core = Path(sys.argv[1]) / "bootable/recovery"
    header = core / "aeraui/include/aeraui/backend.hpp"
    text = header.read_text(encoding="utf-8")
    text = replace_once(text, "int RecoveryMobileSubscription();",
                        "int RecoveryMobileSubscription();\nint RecoveryMobileRadioMode();\n"
                        "bool RecoverySetMobileRadioMode(int mode, std::string *error);")
    header.write_text(text, encoding="utf-8", newline="\n")

    backend = core / "aeraui/platform/aera_backend.cpp"
    text = backend.read_text(encoding="utf-8")
    text = replace_once(text,
        '    else if (key == "mobile_apn") DataManager::SetValue("aera_mobile_apn", value);',
        '    else if (key == "mobile_apn") DataManager::SetValue("aera_mobile_apn", value);\n'
        '    else if (key == "mobile_radio_mode" && (value == "0" || value == "1"))\n'
        '      DataManager::SetValue("aera_mobile_radio_mode", value);')
    text = replace_once(text,
        '         << "mobile_apn=" << DataManager::GetStrValue("aera_mobile_apn") << \'\\n\'\n',
        '         << "mobile_apn=" << DataManager::GetStrValue("aera_mobile_apn") << \'\\n\'\n'
        '         << "mobile_radio_mode=" << RecoveryMobileRadioMode() << \'\\n\'\n')
    text = replace_once(text,
        'bool RecoveryConnectMobile(const std::string &apn, int subscription, std::string *error) {',
        MODE_API + 'bool RecoveryConnectMobile(const std::string &apn, int subscription, std::string *error) {')
    text = replace_once(text,
        '  config["apn"] = apn;\n  config["subscription"] = subscription;',
        '  config["apn"] = apn;\n  config["subscription"] = subscription;\n'
        '  config["radio_mode"] = RecoveryMobileRadioMode();')
    backend.write_text(text, encoding="utf-8", newline="\n")

    scene = core / "aeraui/scenes/mobile_data_scene.cpp"
    text = scene.read_text(encoding="utf-8")
    text = replace_once(text, '  std::array<lv_obj_t *,3> sim{};',
                        '  std::array<lv_obj_t *,3> sim{};\n'
                        '  std::array<lv_obj_t *,2> mode{};\n'
                        '  lv_obj_t *mode_detail=nullptr;\n  int radio_mode=0;')
    text = replace_once(text,
        '  if(mobile.enabled)lv_obj_add_state(state->apn_button,LV_STATE_DISABLED);',
        MODE_REFRESH + '  if(mobile.enabled)lv_obj_add_state(state->apn_button,LV_STATE_DISABLED);')
    text = replace_once(text,
        '  state->apn=RecoveryMobileApn();state->subscription=RecoveryMobileSubscription();',
        '  state->apn=RecoveryMobileApn();state->subscription=RecoveryMobileSubscription();\n'
        '  state->radio_mode=RecoveryMobileRadioMode();')
    text = replace_once(text, '  auto *apn_card=card(configuration);',
                        MODE_CARD + '  auto *apn_card=card(configuration);')
    scene.write_text(text, encoding="utf-8", newline="\n")

    # Keep the existing desktop UI preview shim link-compatible. No tests added.
    preview = core / "aeraui/tests/ui_check.cpp"
    if preview.is_file():
        text = preview.read_text(encoding="utf-8")
        text = replace_once(text, 'int RecoveryMobileSubscription() { return 0; }',
            'int RecoveryMobileSubscription() { return 0; }\n'
            'static int mobile_radio_mode=0;\n'
            'int RecoveryMobileRadioMode() { return mobile_radio_mode; }\n'
            'bool RecoverySetMobileRadioMode(int mode, std::string *) { mobile_radio_mode=mode; return true; }')
        preview.write_text(text, encoding="utf-8", newline="\n")
    print("AERA mobile modes: NR preferred / NR only controls and preference plumbing applied.")


if __name__ == "__main__":
    main()
