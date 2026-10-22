#!/usr/bin/env python3
"""Complete native Chinese messages and regenerate AERA's packed catalog."""

import json
from pathlib import Path
import re
import subprocess
import sys


FORMAT = re.compile(r'%(?:[0-9]+\$)?[-+#0 ]*(?:[0-9]+|\*)?(?:\.(?:[0-9]+|\*))?(?:hh|ll|[hljztL])?[diuoxXfFeEgGaAcspn%]')


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) == 1:
        return text.replace(old, new, 1)
    if old not in text and text.count(new) == 1:
        return text
    raise SystemExit("Chinese UI integration anchor changed; review before applying")


MOBILE_MESSAGES = '''// Translate complete status tags while preserving variable modem diagnostics.
std::string MobileMessage(const std::string &message) {
  struct Pattern { const char *prefix, *suffix, *tag; };
  static const Pattern patterns[] = {
    {"Missing or incompatible kernel module: ", "", "Missing or incompatible kernel module: %s"},
    {"Required modem service ", " is unavailable", "Required modem service %s is unavailable"},
    {"Mobile connection lost. Retrying in ", " seconds", "Mobile connection lost. Retrying in %s seconds"},
    {"Modem transport send failed: ", "", "Modem transport send failed: %s"},
  };
  for (const auto &pattern : patterns) {
    const std::string prefix = pattern.prefix, suffix = pattern.suffix;
    if (message.size() >= prefix.size() + suffix.size() &&
        message.compare(0, prefix.size(), prefix) == 0 &&
        message.compare(message.size() - suffix.size(), suffix.size(), suffix) == 0) {
      const auto value = message.substr(prefix.size(), message.size() - prefix.size() - suffix.size());
      return i18n::Format(pattern.tag, value.c_str());
    }
  }
  constexpr const char *qmi = "QMI error ";
  if (message.compare(0, std::string(qmi).size(), qmi) == 0) {
    const auto reason = message.find(" [call reason ");
    if (reason != std::string::npos && message.back() == ']') {
      const auto code = message.substr(std::string(qmi).size(), reason - std::string(qmi).size());
      const auto detail = message.substr(reason + 14, message.size() - reason - 15);
      return i18n::Format("QMI error %s [call reason %s]", code.c_str(), detail.c_str());
    }
    return i18n::Format("QMI error %s", message.substr(std::string(qmi).size()).c_str());
  }
  return i18n::Translate(message.c_str());
}
'''


def patch_mobile(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if MOBILE_MESSAGES not in text:
        text = replace_once(text, "struct MobileUi {", MOBILE_MESSAGES + "struct MobileUi {")
    replacements = [
        ('lv_label_set_text(state->detail,i18n::Translate(detail.c_str()));',
         'lv_label_set_text(state->detail,MobileMessage(detail).c_str());'),
        ('if(network.empty())network="Not connected";',
         'if(network.empty())network=i18n::Translate("Not connected");'),
        ('std::to_string(mobile.signal_dbm)+" dBm":"Signal unavailable";',
         'std::to_string(mobile.signal_dbm)+" dBm":i18n::Translate("Signal unavailable");'),
        ('lv_label_set_text(state->apn_text,state->apn.empty()?"Automatic":state->apn.c_str());',
         'lv_label_set_text(state->apn_text,state->apn.empty()?i18n::Translate("Automatic"):state->apn.c_str());'),
        ('i18n::Translate(mobile.message.c_str()),&lv_font_montserrat_28,kRed);',
         'MobileMessage(mobile.message).c_str(),&lv_font_montserrat_28,kRed);'),
        ('else lv_label_set_text(error,i18n::Translate(message.c_str()));',
         'else lv_label_set_text(error,MobileMessage(message).c_str());'),
        ('lv_textarea_set_placeholder_text(input,"Automatic");',
         'lv_textarea_set_placeholder_text(input,i18n::Translate("Automatic"));'),
    ]
    for old, new in replacements:
        text = replace_once(text, old, new)
    path.write_text(text, encoding="utf-8", newline="\n")


def patch_fonts(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_once(text,
        'SetText(row.note, item.face.subset + " / " + FaceName(item.face) + badge +',
        'SetText(row.note, std::string(i18n::Translate(item.face.subset.c_str())) + " / " + FaceName(item.face) + badge +')
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <AERA source root>")
    core = Path(sys.argv[1]) / "bootable/recovery"
    catalog_dir = core / "aeraui/localization/catalog"
    catalog_path = catalog_dir / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if catalog.get("schema") != 1 or "zh_CN" not in catalog.get("languages", []):
        raise SystemExit("Unsupported AERA catalog schema")
    overlay = json.loads(Path(__file__).with_name("aera_chinese.json").read_text(encoding="utf-8"))
    rows = catalog["strings"]
    for key, translations in overlay.items():
        if not key or not isinstance(translations, dict):
            raise SystemExit("Invalid Chinese catalog overlay")
        row = rows.setdefault(key, {})
        for locale, text in translations.items():
            if locale not in ("zh_CN", "zh_TW") or not text or "\0" in text:
                raise SystemExit("Invalid Chinese translation: " + key)
            if FORMAT.findall(key) != FORMAT.findall(text):
                raise SystemExit("Translation format arguments differ: " + key)
            row[locale] = text
    patch_mobile(core / "aeraui/scenes/mobile_data_scene.cpp")
    patch_fonts(core / "aeraui/scenes/font_browser.cpp")
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    subprocess.run([sys.executable, str(catalog_dir / "generate_catalog.py"),
                    "--recovery", str(core), "--output", str(catalog_dir / "catalog_generated.cpp")], check=True)
    generated = catalog_dir / "catalog_generated.cpp"
    generated.write_text(generated.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    print(f"AERA Chinese UI: {len(overlay)} native messages supplemented; packed catalog regenerated.")


if __name__ == "__main__":
    main()
