#!/usr/bin/env python3
"""Use Qualcomm's stored TOD offset even when the raw RTC looks recent."""

from pathlib import Path
import sys


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <bootable/recovery directory>")

    source = Path(sys.argv[1]) / "twrp-functions.cpp"
    text = source.read_text(encoding="utf-8")
    start = text.index("#ifndef OF_USE_LEGACY_TIME_FIXUP\n")
    end = text.index("#endif // ifndef OF_USE_LEGACY_TIME_FIXUP", start)
    function = text[start:end]
    old = (
        "\t\tif (tv.tv_sec > 1517600000) { // Anything older then 2 Feb 2018 19:33:20 GMT will do nicely thank you ;)\n"
        "\n"
        '\t\t\tLOGINFO("TWFunc::Fixup_Time: Date and time corrected: %s\\n", TWFunc::Get_Current_Date().c_str());\n'
        "\t\t\tfixed = true;\n"
        "\t\t\treturn;\n"
        "\n"
        "\t\t}\n"
    )
    new = (
        "\t\t// infiniti stores real UTC as raw RTC + /data/vendor/time/ats_2.\n"
        "\t\t// A recent RTC year does not mean its Qualcomm TOD offset is zero.\n"
        "\t\t// Leave fixed false until the offset below is actually available;\n"
        "\t\t// the normal post-decryption startup calls this function again.\n"
    )
    if new in function:
        print("AERA already applies the Qualcomm TOD offset to a recent RTC.")
        return
    if function.count(old) != 1:
        raise SystemExit("The Qualcomm RTC early-return logic changed; review before patching")
    text = text[:start] + function.replace(old, new, 1) + text[end:]
    source.write_text(text, encoding="utf-8", newline="\n")
    print("AERA applies Qualcomm TOD offsets instead of trusting the raw RTC year.")


if __name__ == "__main__":
    main()
