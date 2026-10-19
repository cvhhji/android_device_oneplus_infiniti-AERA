#!/usr/bin/env python3
"""Preserve all resolv.conf DNS servers in AERA's recovery Bionic resolver."""

from pathlib import Path
import sys


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <AERA source root>")
    source = Path(sys.argv[1]) / "bionic/libc/dns/resolv/res_init.c"
    text = source.read_text(encoding="utf-8")
    old = "\t_resolv_load_external_dns(statp);\n"
    new = (
        old
        + "\t/* Keep the external server count when res_ninit finishes below. */\n"
        + "\tnserv = statp->nscount;\n"
    )
    if new in text:
        print("AERA Bionic already preserves the external DNS server count.")
        return
    if text.count(old) != 1:
        raise SystemExit("Could not locate the AERA external DNS loader call")
    final_count = "\tif (nserv > 0) {\n\t\tstatp->nscount = nserv;"
    if text.count(final_count) != 1:
        raise SystemExit("AERA resolver finalization changed; review before patching")
    source.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    print("AERA Bionic keeps all configured DNS servers for timeout fallback.")


if __name__ == "__main__":
    main()
