#!/usr/bin/env bash
set -euo pipefail

repository=${1:?Usage: publish_aera_plugin_mirror.sh <owner/repository>}
workspace=${GITHUB_WORKSPACE:-$(git rev-parse --show-toplevel)}
runner_temp=${RUNNER_TEMP:-${TMPDIR:-/tmp}}
work_dir=$(mktemp -d "${runner_temp%/}/aera-plugin-mirror.XXXXXX")
asset_dir="$work_dir/assets"
keep_file="$work_dir/keep-assets.txt"
tag=aera-plugins-mirror

mkdir -p "$asset_dir"
python3 "$workspace/tools/mirror_aera_plugins.py" \
  --output "$asset_dir" --keep-file "$keep_file"

if ! gh release view "$tag" --repo "$repository" >/dev/null 2>&1; then
  gh release create "$tag" \
    --repo "$repository" \
    --target "${GITHUB_SHA:-HEAD}" \
    --title "AERA signed plugin mirror" \
    --notes "Mirrored AERA's signed catalog and checksum-pinned plugin packages. The recovery verifies the original catalog and package signatures and hashes." \
    --prerelease
fi

mapfile -t package_assets < <(
  find "$asset_dir" -maxdepth 1 -type f \
    ! -name 'catalog.json' ! -name 'catalog.json.sig' -print | sort
)
if ((${#package_assets[@]})); then
  gh release upload "$tag" "${package_assets[@]}" \
    --repo "$repository" --clobber
fi
gh release upload "$tag" \
  "$asset_dir/catalog.json" "$asset_dir/catalog.json.sig" \
  --repo "$repository" --clobber

while IFS=$'\t' read -r asset_id asset_name; do
  [[ -n "$asset_id" && -n "$asset_name" ]] || continue
  if ! grep -Fqx -- "$asset_name" "$keep_file"; then
    gh api --method DELETE "repos/$repository/releases/assets/$asset_id" >/dev/null
  fi
done < <(gh release view "$tag" --repo "$repository" \
  --json assets --jq '.assets[] | [.id, .name] | @tsv')

echo "Updated $repository release $tag with ${#package_assets[@]} verified plugin package assets."

if [[ -n "${GITEE_TOKEN:-}" ]]; then
  gitee_repository=${GITEE_REPOSITORY:-zaomi/android_device_oneplus_infiniti-AERA}
  python3 "$workspace/tools/publish_aera_gitee_release.py" \
    "$gitee_repository" "$asset_dir" "$tag" \
    "AERA signed plugin mirror" \
    "Mirrored AERA's signed catalog and checksum-pinned plugin packages. The recovery verifies the original catalog and package signatures and hashes." \
    "aera-16.0"
else
  echo "GITEE_TOKEN is not configured; skipping the Gitee plugin mirror."
fi
