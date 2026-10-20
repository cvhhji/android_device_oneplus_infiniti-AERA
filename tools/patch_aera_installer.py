#!/usr/bin/env python3
"""Limit the infiniti installer to the recovery slot that actually booted."""

from pathlib import Path
import re
import sys


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <extracted installer directory>")
    source = Path(sys.argv[1]) / "META-INF/com/google/android/update-binary"
    text = source.read_text(encoding="utf-8")
    if not re.search(r'^TARGET_DEVICE="infiniti"$', text, re.MULTILINE):
        raise SystemExit("Refusing to change an installer for a different device")
    marker = "# infiniti: update only the recovery slot that actually booted."
    if marker in text:
        print("The infiniti installer already writes only the booted recovery slot.")
        return
    start = '\tif [ "$name" = "recovery" ]; then\n'
    end = '\n# vendor_boot as recovery - flash both slots and return\n'
    if text.count(start) != 1 or text.count(end) != 1:
        raise SystemExit("Recovery installer boundaries changed; review before patching")
    first = text.index(start)
    last = text.index(end, first)
    if text[first:last].count("for slot in _a _b; do") != 1:
        raise SystemExit("Expected exactly one dual-slot recovery install loop")
    replacement = '''\t# infiniti: update only the recovery slot that actually booted.
\t[ "$name" = "recovery" ] || abort "This infiniti package requires dedicated recovery partitions."
\tif [ "$name" = "recovery" ]; then
\t   tmp=$($GETPROP "ro.boot.slot_suffix")
\t   case "$tmp" in
\t      _a|_b) ;;
\t      *)
\t         tmp=$($GETPROP "ro.boot.slot")
\t         case "$tmp" in
\t            a|b) tmp="_$tmp" ;;
\t            _a|_b) ;;
\t            *) abort "Cannot determine the booted slot; no recovery partition was written." ;;
\t         esac
\t         ;;
\t   esac
\t   PART="$target$tmp"
\t   [ -b "$PART" ] || abort "The booted recovery partition is missing: $PART"
\t   part_size=$(blockdev --getsize64 "$PART") || abort "Cannot read the booted recovery partition size."
\t   local rec_size=$(FileSize "recovery.img")
\t   case "$part_size:$rec_size" in
\t      *[!0-9:]*|:*|*:) abort "Invalid recovery image or partition size." ;;
\t   esac
\t   [ "$rec_size" -gt 0 ] && [ "$rec_size" -le "$part_size" ] || abort "The recovery image does not fit the booted partition."
\t   ui_print "- Active-slot recovery update: $tmp"
\t   ui_print "- Installing AERA to slot $tmp only..."
\t   blockdev --setrw "$PART" || abort "Cannot make the booted recovery partition writable."
\t   package_extract_file "recovery.img" "$PART" || abort "Writing the booted recovery partition failed."
\t   return
\tfi
'''
    text = text[:first] + replacement + text[last:]
    text = text.replace(
        "# if we have a recovery  partition - install the recovery image to recovery _a /_b",
        "# Update the dedicated recovery partition of the booted slot.",
        1,
    )
    source.write_text(text,
                      encoding="utf-8", newline="\n")
    print("Infiniti recovery installer writes only ro.boot.slot_suffix and rejects an unknown slot.")


if __name__ == "__main__":
    main()
