---
version: alpha
name: AERA native recovery controls
description: Native LVGL recovery screens using AERA's graphite cards and cyan selection.
colors:
  accent: "#16C8FF"
  canvas: "#202226"
  card: "#2D3036"
  control: "#34373D"
  text: "#F5F7FA"
  muted: "#AEB6C0"
typography:
  sans:
    fontFamily: "Montserrat with AERA language fallback"
rounded:
  card: "36 LVGL units"
  control: "30 LVGL units"
spacing:
  page-inset: "64 LVGL units"
  card-padding: "40 LVGL units"
  row-gap: "28 LVGL units"
components:
  button: { owner: "aeraui/components/ui_components.hpp" }
  card: { owner: "aeraui/scenes/mobile_data_scene.cpp" }
---

# AERA native recovery controls

## Overview

This device tree adapts the pinned AERA recovery sources listed in
`tools/aera-upstream-lock.xml`. The native LVGL implementation owns appearance;
this document records its existing contracts and does not generate tokens.
The phone screenshot supplied on 2026-10-23 is the visual reference.

The current change adds two network-mode choices to the existing mobile-data
page. It is a recovery tool for device owners, with Simplified Chinese as the
default and Traditional Chinese translations for new messages. It is not a web
page. Browser popups, CSS, ARIA and desktop viewport assumptions do not apply.

## Runtime owners and layout

Shared tokens remain in upstream `aeraui/components/design.hpp`. `kAccent`,
`kMainSheet`, `kMainPanel`, `kText`, `kMuted` and `UiFont` implement the values
above, including theme changes and language fallback. New controls reuse
`widgets::Button`, `Panel` and `Interactive`; they introduce no independent
palette, fonts, animations or icon family.

The mobile page uses a scrollable vertical stack in portrait and the existing
two-column layout in landscape. The network-mode card sits between SIM selection
and APN configuration. Its two equal-width buttons use the existing SIM-button
geometry and selected/disabled styling. Help text wraps inside the card.

## Canonical UI map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select/Listbox | Native LVGL Button group in mobile_data_scene.cpp | Existing SIM-selection group | Two network-mode choices | Source review, Actions compile, device interaction pending |
| Form | Recovery mobile backend and provider request validation | Validated radio_mode 0 or 1 | Disconnected settings only | Source review and device validation pending |
| Toast | Existing mobile detail label and provider status | RecoveryMobileStatus and MobileMessage | Persistent translated status/error | Device validation pending |

## Behavior and feedback

“5G preferred” is the default. “5G only” requires standalone NR service and must
not silently connect over LTE. The selected option is saved in AERA preferences;
the modem policy is temporary for the recovery connection and the original mode
and acquisition order are restored on disconnect. Modem rejection/readback
mismatch is an error, not a successful selection.

Mode controls are disabled while mobile data or a SIM switch is active. Their
help text explains how to enable them and warns that NR-only coverage is needed.
Changing a disconnected option is reversible and needs no confirmation dialog.
Failed saves retain the previous selection and use the existing error label.

## Verification boundary

UI source changes are applied by `tools/patch_aera_radio_modes.py` against pinned
upstream anchors before Chinese catalog generation. Android/C++ builds run only
in GitHub Actions. Source inspection cannot establish touch behavior, clipping,
actual network registration, restoration or operator-name rendering. Those need
the signed new image on the device; the existing build35 screenshot is not proof
of the new controls.
