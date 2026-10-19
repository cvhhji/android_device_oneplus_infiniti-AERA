# infiniti recovery time

The Qualcomm RTC on this device is not the complete UTC clock. Android stores
the signed 64-bit time-of-day offset in milliseconds in
`/data/vendor/time/ats_2`; UTC is the RTC value plus this offset.

On the inspected phone, the raw RTC reported 2026-10-12 while UTC was
2026-10-19. Its `ats_2` offset was 589049161 milliseconds. Adding it to the
RTC agreed with the host UTC clock within one second. The UTC+8 timezone
and 24-hour preference were already correct.

`patch_aera_time.py` removes the non-legacy clock fixup's early return that
treated every RTC date after February 2018 as accurate. The existing code
can then read `ats_2` and apply it to the raw RTC. It marks the correction
complete only after reading the offset, so an early call before userdata
is available does not suppress the normal call after `Decrypt_Page()`.
Each attempt starts from the raw RTC, preventing repeated offset addition.
No hardware RTC or Android offset file is written.

OTA catalog `build_time` must equal the installed image's
`ro.build.date.utc_aera`, obtained from `META-INF/debug/default.prop` in the
installer ZIP. Using the later packaging time advertises the same build
again after installation; the clock shown in the status bar is unrelated
to that version comparison.
