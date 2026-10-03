#!/usr/bin/env python3
from pathlib import Path
import sys


TIMEZONE = "TAIST-8"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0 and new in text:
        return text
    if count != 1:
        raise SystemExit(f"Expected one source match for {label}; found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <bootable/recovery directory>")

    recovery = Path(sys.argv[1])
    data_cpp = recovery / "data.cpp"
    if not data_cpp.is_file():
        raise SystemExit(f"AERA recovery source not found: {data_cpp}")

    text = data_cpp.read_text(encoding="utf-8")
    old_timezone = (
        "\tstring TZ = GetStrValue(TW_TIME_ZONE_VAR);\n"
        '\tsetenv("TZ", TZ.c_str(), 1);\n'
    )
    new_timezone = (
        "\tstring TZ = GetStrValue(TW_TIME_ZONE_VAR);\n"
        f'\tif (TZ.rfind("{TIMEZONE}", 0) == 0) {{\n'
        f'\t\tTZ = "{TIMEZONE}";\n'
        "\t\tSetValue(TW_TIME_ZONE_VAR, TZ);\n"
        f'\t\tSetValue(TW_TIME_ZONE_GUISEL, "{TIMEZONE};");\n'
        '\t\tSetValue(TW_TIME_ZONE_GUIDST, "0");\n'
        "\t}\n"
        '\tsetenv("TZ", TZ.c_str(), 1);\n'
    )
    text = replace_once(text, old_timezone, new_timezone, "UTC+8 saved-timezone migration")
    text = replace_once(
        text,
        '  mPersist.SetValue(TW_TIME_ZONE_GUIDST, "1");',
        '  mPersist.SetValue(TW_TIME_ZONE_GUIDST, "0");',
        "daylight-saving default",
    )
    text = replace_once(
        text,
        "  mPersist.SetValue(TW_TIME_ZONE_GUISEL, OF_DEFAULT_TIMEZONE);",
        f'  mPersist.SetValue(TW_TIME_ZONE_GUISEL, "{TIMEZONE};");',
        "timezone selector default",
    )
    text = replace_once(
        text,
        '  mPersist.SetValue("tw_military_time", "0");',
        '  mPersist.SetValue("tw_military_time", "1");',
        "24-hour clock default",
    )
    data_cpp.write_text(text, encoding="utf-8", newline="\n")

    print("Applied zh_CN, UTC+8 without DST, and 24-hour clock defaults.")


if __name__ == "__main__":
    main()
