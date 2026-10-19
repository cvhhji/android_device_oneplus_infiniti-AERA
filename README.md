# AERA Recovery Project device tree for OnePlus 15

Device codename: `infiniti`

Platform: Qualcomm SM8850 (`canoe`)
Recovery partition limit: 100 MiB

This tree preserves the history of the original OrangeFox device tree while
carrying the OnePlus 15 integration for AERA Recovery Project R1.0.

## Hardware support

- Display and touch
- File-based encryption
- A/B flashing, backup/restore, ADB, MTP, and fastbootd
- Wi-Fi
- Haptics and flashlight
- Adreno 840 recovery rendering with matching gen80200 firmware
- Qualcomm AGM/PAL audio using the installed OP15 stock partitions
- KernelSU, KernelSU Next, and SukiSU Ultra support

The proprietary graphics and audio files in this repository were extracted
from the matching OnePlus 15 stock OTA. Do not reuse them on another platform.

## GitHub Actions builds and releases

Pushing to `aera-16.0` or starting **Build AERA Recovery infiniti** manually
syncs the AERA `aera-16.0` Android 16 source and builds on GitHub Actions. The
`17.0` text is the requested artifact and release naming; it does not change
the upstream Android 16 source branch.

Each successful build publishes the AVB-transplanted recovery image, the
matching signed AERA installer ZIP, SHA256SUMS, and stable/nightly update
catalogs to a GitHub Release. The in-recovery updater reads those catalogs
from this repository's latest release. A separate daily action mirrors the
signed AERA plugin catalog and its hash-pinned packages to the prerelease
`aera-plugins-mirror`, while preserving the AERA signature and SHA-256 checks.

The build defaults to Simplified Chinese, Beijing time (UTC+8 without daylight
saving), and a 24-hour clock. GitHub-hosted Release downloads still depend on
GitHub being reachable from the phone's network; a Gitee or China-hosted CDN
endpoint would be needed to guarantee access on networks that block GitHub.
