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

## Recovery DNS fallback

`tools/patch_aera_resolver.py` repairs the AERA Bionic resolver used by the
cloud build. Its external DNS loader reads up to three servers from
`/etc/resolv.conf`, but the end of `__res_vinit()` overwrites `nscount` with
the initial default-server count. On the inspected arm64 recovery this was
one: strace showed only the unresponsive DHCP DNS being queried, even
though the file also contained mainland public resolvers.

Preserve the external loader's server count so the existing resolver retry
loop can reach the other configured servers. DHCP DNS remains first; no
Gitee/CDN addresses are hardcoded, and HTTPS verification stays enabled.
The curl child uses `RES_OPTIONS=timeout:2 attempts:2` to bound DNS retries.
