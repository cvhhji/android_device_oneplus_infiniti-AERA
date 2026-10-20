# infiniti recovery updates

## Whole-package download progress

The HTTPS callback receives the current part's bytes. OTA transfers also pass
the number of bytes in completed parts and the complete package size, so the
visible amount is `completed + current_part` and the percentage uses the full
package as its denominator. Transfer retries retain their highest reported
amount. The subsequent local copy into the assembly file does not report its
first block as a new, lower download amount.

The plugin multipart implementation follows the same rule. Size, signature,
TLS and final SHA-256 checks remain in their existing paths.

## Installation target

`patch_aera_installer.py` runs on the extracted installer before the workflow
creates and signs the final ZIP. Its dedicated-recovery branch writes only
the slot in the running boot's `ro.boot.slot_suffix` (`ro.boot.slot` is a
fallback). An unknown slot or missing/undersized partition aborts installation.
It neither selects the UI's alternate slot nor switches the boot slot.

The restriction is in the signed installer itself. Updating from an older
recovery therefore already uses the new policy, even though the old recovery's
download display is still running. The generated infiniti installer also uses
this policy when the same ZIP is installed manually.

Validate a release by recording both recovery partition hashes before the
native OTA, verifying the ZIP signature and active-slot install log, then
checking that the booted slot contains the new image while the other slot's
hash is unchanged. Preserve the official AVB metadata and verify the new
image's build timestamp against the stable and nightly catalogs.
