#!/usr/bin/env bash
set -euo pipefail

repository=${1:?Usage: publish_aera_gitee_branch.sh <owner/repository> <branch> <asset-directory>}
branch=${2:?Missing Gitee asset branch}
asset_dir=${3:?Missing asset directory}
if [[ ! "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "Invalid Gitee repository: $repository" >&2
  exit 2
fi
if [[ ! "$branch" =~ ^[A-Za-z0-9._/-]+$ || "$branch" == *..* ]]; then
  echo "Invalid Gitee asset branch: $branch" >&2
  exit 2
fi
if [[ ! -d "$asset_dir" ]]; then
  echo "Asset directory does not exist: $asset_dir" >&2
  exit 2
fi
if [[ -z "${GITEE_TOKEN:-}" ]]; then
  echo "GITEE_TOKEN is required to publish a Gitee asset branch" >&2
  exit 2
fi

temporary_root=${RUNNER_TEMP:-${TMPDIR:-/tmp}}
work_dir=$(mktemp -d "${temporary_root%/}/aera-gitee-branch.XXXXXX")
checkout="$work_dir/repository"
manifest="$work_dir/assets-manifest.txt"
remote_manifest="$work_dir/remote-assets-manifest.txt"
remote_url="https://gitee.com/$repository.git"
raw_manifest_url="https://gitee.com/$repository/raw/$branch/assets-manifest.txt"

(
  cd "$asset_dir"
  find . -maxdepth 1 -type f ! -name assets-manifest.txt -print0 \
    | sort -z | xargs -0 -r sha256sum
) > "$manifest"
if [[ ! -s "$manifest" ]]; then
  echo "No files found to publish from $asset_dir" >&2
  exit 2
fi

total_bytes=0
while IFS= read -r -d '' path; do
  size=$(stat -c '%s' "$path")
  if ((size > 50000000)); then
    echo "Gitee free repository file limit exceeded: $(basename "$path") ($size bytes)" >&2
    exit 2
  fi
  total_bytes=$((total_bytes + size))
done < <(find "$asset_dir" -maxdepth 1 -type f -print0)
if ((total_bytes > 400000000)); then
  echo "Gitee asset branch exceeds the 400 MB safety limit ($total_bytes bytes)" >&2
  exit 2
fi

if curl --fail --silent --show-error --location --max-time 60 \
    "$raw_manifest_url" --output "$remote_manifest" 2>/dev/null &&
    cmp --silent "$manifest" "$remote_manifest"; then
  echo "Gitee branch $branch already matches the verified asset set."
  exit 0
fi

mkdir -p "$checkout"
cp -a "$asset_dir"/. "$checkout"/
cp "$manifest" "$checkout/assets-manifest.txt"
git -C "$checkout" init --quiet --initial-branch "$branch"
git -C "$checkout" config user.name "ZAOMI"
git -C "$checkout" config user.email "206011819+cvhhji@users.noreply.github.com"
git -C "$checkout" add --all
git -C "$checkout" commit --quiet -m "Mirror AERA verified assets"

cat > "$work_dir/gitee-askpass.sh" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  *Username*) printf '%s\n' "$GITEE_USERNAME" ;;
  *Password*) printf '%s\n' "$GITEE_TOKEN" ;;
  *) exit 1 ;;
esac
EOF
chmod 700 "$work_dir/gitee-askpass.sh"
export GITEE_USERNAME=${GITEE_USERNAME:-zaomi}
export GIT_ASKPASS="$work_dir/gitee-askpass.sh"
export GIT_TERMINAL_PROMPT=0
git -C "$checkout" remote add origin "$remote_url"
git -C "$checkout" push --force origin "HEAD:refs/heads/$branch"
echo "Published $(wc -l < "$manifest") verified files to Gitee branch $branch ($total_bytes bytes)."
