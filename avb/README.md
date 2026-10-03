# OnePlus 15 infiniti recovery AVB metadata

`recovery-vbmeta.bin` is the 2,240-byte `AVB0` metadata payload used by the
same-device OrangeFox recovery workflow. Its SHA-256 is
`487f9dc3db6e611205a19d44abd845b4ba59c308ad4bb227137c471af38150b8`.

The AERA GitHub Actions workflow places this payload into the 100 MiB recovery
image after `recoveryimage` completes, then verifies the AVB footer and embedded
metadata before uploading the artifact.
