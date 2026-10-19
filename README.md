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
catalogs to GitHub Releases. When configured, the recovery image and update
catalogs are also mirrored to Gitee for mainland downloads. The updater uses
Gitee first and falls back to this GitHub repository.

The signed plugin catalog, its signature, and all hash-pinned packages are
stored in `vendor/aera-plugins/` on this branch. The recovery's plugin manager
downloads these repository files from Gitee Raw first and GitHub Raw as a
fallback, then checks the catalog signature and package hashes. Update the
catalog and package files together when refreshing the plugin set.

To enable Gitee publishing and source-branch mirroring, add a Gitee personal
access token with repository write access as the GitHub Actions secret
`GITEE_TOKEN`. The Gitee repository is
`zaomi/android_device_oneplus_infiniti-AERA`.

The build defaults to Simplified Chinese, Beijing time (UTC+8 without daylight
saving), and a 24-hour clock. Gitee provides a mainland-accessible mirror; the
GitHub release remains available as a fallback.
