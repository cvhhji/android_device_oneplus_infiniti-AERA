# HTTPS trust store

`cacert.pem` is the Mozilla CA root bundle distributed by curl:

- Download: https://curl.se/ca/cacert.pem
- Source details: https://curl.se/docs/caextract.html
- Mozilla certificate data date: 2026-09-25
- Retrieved: 2026-10-19
- SHA-256: `a41b5d356aea97a529fe27e0f7316d2f9d946d75927476cf9cf1b90637d00505`
- Certificate data license: Mozilla Public License 2.0,
  https://www.mozilla.org/MPL/2.0/

The recovery curl client verifies certificates and host names with this bundle.
Refresh the complete bundle from its upstream source and update this digest
together. No private CA keys or client credentials belong here.
