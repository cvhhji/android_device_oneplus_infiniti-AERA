#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <AVB0 vbmeta file> <built recovery.img> <output.img>" >&2
  exit 2
}

fail() {
  echo "AVB transplant: $*" >&2
  exit 1
}

[[ $# -eq 3 ]] || usage
source_vbmeta=$1
target_image=$2
output_image=$3

[[ -f "$source_vbmeta" ]] || fail "vbmeta source not found: $source_vbmeta"
[[ -f "$target_image" ]] || fail "target image not found: $target_image"
[[ "$target_image" != "$output_image" ]] || fail "output must not overwrite the input image"

get_be64() {
  local file=$1 offset=$2 hex
  hex=$(od -An -N8 -tx1 -j "$offset" "$file" | tr -d ' \t\r\n')
  [[ "$hex" =~ ^[0-9a-fA-F]{16}$ ]] || fail "cannot read 64-bit field at $offset from $file"
  printf '%d' "$((16#$hex))"
}

write_be64() {
  local value=$1 file=$2 shift byte octal
  for shift in 56 48 40 32 24 16 8 0; do
    byte=$(((value >> shift) & 255))
    printf -v octal '%03o' "$byte"
    printf '%b' "\\$octal" >> "$file"
  done
}

source_size=$(stat -c '%s' "$source_vbmeta")
[[ $(dd if="$source_vbmeta" bs=1 count=4 status=none) == AVB0 ]] || fail "source does not start with AVB0"
auth_size=$(get_be64 "$source_vbmeta" 12)
aux_size=$(get_be64 "$source_vbmeta" 20)
vbmeta_size=$((256 + auth_size + aux_size))
(( vbmeta_size == source_size )) || fail "source vbmeta size does not match its header"

target_size=$(stat -c '%s' "$target_image")
(( target_size >= 64 )) || fail "target is too small to contain an AVB footer"
footer_offset=$((target_size - 64))
footer_magic=$(dd if="$target_image" bs=1 skip="$footer_offset" count=4 status=none)
[[ "$footer_magic" == AVBf ]] || fail "built image has no AVB footer"

original_size=$(get_be64 "$target_image" $((footer_offset + 12)))
(( original_size <= footer_offset )) || fail "target footer has an invalid original image size"
(( original_size + vbmeta_size <= footer_offset )) || fail "vbmeta does not fit in the target partition"
padding_size=$((footer_offset - original_size - vbmeta_size))

output_dir=$(dirname "$output_image")
mkdir -p "$output_dir"
tmp_image=$(mktemp "$output_image.tmp.XXXXXX")
tmp_footer=$(mktemp)
cleanup() {
  rm -f "$tmp_image" "$tmp_footer"
}
trap cleanup EXIT

head -c "$original_size" "$target_image" > "$tmp_image"
cat "$source_vbmeta" >> "$tmp_image"
if (( padding_size > 0 )); then
  head -c "$padding_size" /dev/zero >> "$tmp_image"
fi

printf 'AVBf\000\000\000\001\000\000\000\000' > "$tmp_footer"
write_be64 "$original_size" "$tmp_footer"
write_be64 "$original_size" "$tmp_footer"
write_be64 "$vbmeta_size" "$tmp_footer"
head -c 28 /dev/zero >> "$tmp_footer"
cat "$tmp_footer" >> "$tmp_image"

[[ $(stat -c '%s' "$tmp_image") -eq "$target_size" ]] || fail "output size changed"
[[ $(tail -c 64 "$tmp_image" | head -c 4) == AVBf ]] || fail "output footer check failed"
[[ $(dd if="$tmp_image" bs=1 skip="$original_size" count=4 status=none) == AVB0 ]] || fail "output vbmeta check failed"

mv -f "$tmp_image" "$output_image"
trap - EXIT
rm -f "$tmp_footer"
echo "AVB metadata transplanted into $output_image"
