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
catalogs can be published to Gitee with a direct Git push. The updater uses
Gitee first and falls back to this GitHub repository.

The signed plugin catalog, its signature, and all hash-pinned packages are
stored in `vendor/aera-plugins/` on this branch. The recovery's plugin manager
downloads these repository files from Gitee Raw first and GitHub Raw as a
fallback, then checks the catalog signature and package hashes. Update the
catalog and package files together when refreshing the plugin set.

Gitee requires login for anonymous Raw downloads of large files, even when
they were uploaded with Git. Packages larger than 8 MiB therefore also have
8 MiB `.part0`, `.part1`, ... files next to the complete original package.
The recovery downloads and joins the parts automatically, then validates the
complete package against its size and SHA-256 from the signed catalog. The
GitHub fallback downloads the complete original package.

Plugin and OTA transfers use the Android curl client with the Mozilla CA
bundle, HTTPS-only redirects, IPv4 resolution, bounded connection/transfer
timeouts, and cleanup of the entire download process group. Transfer status
is reported explicitly even when recovery's global SIGCHLD handler reaps a
child. Multipart progress updates while each part downloads. DHCP DNS is
preserved, with mainland public resolvers ahead of overseas fallback servers.
Package retries resume partial data when the server supports HTTP Range.

To refresh the Gitee plugin mirror, run
`python3 tools/prepare_aera_plugin_parts.py`, commit the catalog, packages,
and generated parts, then push `aera-16.0` directly to
`https://gitee.com/zaomi/android_device_oneplus_infiniti-AERA.git`.
This plugin upload does not use GitHub Actions. Recovery image compilation
and GitHub Release publication continue to run in GitHub Actions.

The build defaults to Simplified Chinese, Beijing time (UTC+8 without daylight
saving), and a 24-hour clock. Gitee provides a mainland-accessible mirror; the
GitHub release remains available as a fallback.
