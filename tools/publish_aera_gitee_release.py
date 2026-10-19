#!/usr/bin/env python3
"""Publish an asset directory to a Gitee Release using a token from Actions."""

import re
import os
from pathlib import Path
import sys
import time
from urllib.parse import quote

import requests


API_ROOT = "https://gitee.com/api/v5"
GITEE_ROOT = "https://gitee.com"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
TAG_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def request(session: requests.Session, method: str, url: str, **kwargs):
    timeout = kwargs.pop("timeout", (30, 900))
    response = session.request(method, url, timeout=timeout, **kwargs)
    if not response.ok:
        body = response.text[:1500]
        raise RuntimeError(
            f"Gitee API {method} {response.status_code} for {url}: {body}"
        )
    return response


def get_release(session: requests.Session, repository: str, tag: str):
    url = f"{API_ROOT}/repos/{repository}/releases/tags/{quote(tag, safe='')}"
    response = session.get(url, timeout=(30, 90))
    if response.status_code == 404:
        return None
    if not response.ok:
        raise RuntimeError(
            f"Gitee release lookup failed ({response.status_code}): "
            f"{response.text[:1500]}"
        )
    return response.json()


def ensure_release(
    session: requests.Session,
    repository: str,
    tag: str,
    title: str,
    notes: str,
    target_commitish: str,
):
    release = get_release(session, repository, tag)
    if release is not None:
        return int(release["id"])

    url = f"{API_ROOT}/repos/{repository}/releases"
    response = request(
        session,
        "POST",
        url,
        data={
            "tag_name": tag,
            "name": title,
            "body": notes,
            "target_commitish": target_commitish,
            "prerelease": "false",
        },
    )
    payload = response.json()
    if "id" not in payload:
        raise RuntimeError("Gitee created a release without returning its ID")
    return int(payload["id"])


def list_attachments(session: requests.Session, repository: str, release_id: int):
    url = f"{API_ROOT}/repos/{repository}/releases/{release_id}/attach_files"
    response = request(session, "GET", url, params={"per_page": 100})
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("Gitee returned an invalid release attachment list")
    return payload


def upload_attachment(
    session: requests.Session, repository: str, release_id: int, path: Path
):
    url = f"{API_ROOT}/repos/{repository}/releases/{release_id}/attach_files"
    for attempt in range(1, 4):
        try:
            with path.open("rb") as stream:
                response = request(
                    session,
                    "POST",
                    url,
                    # Requests uses the connection timeout while writing the
                    # multipart body, so large assets need a generous value.
                    timeout=(1800, 1800),
                    files={"file": (path.name, stream, "application/octet-stream")},
                )
            return response.json()
        except requests.RequestException as error:
            # The server may finish storing an asset even if the runner loses
            # the response while sending a large file. Check before retrying.
            try:
                attachments = list_attachments(session, repository, release_id)
            except requests.RequestException:
                attachments = []
            for attachment in attachments:
                if attachment.get("name") != path.name:
                    continue
                size = attachment.get("size")
                if size is None or int(size) == path.stat().st_size:
                    print(
                        f"Verified {path.name} on Gitee after the upload response was lost"
                    )
                    return attachment

            if attempt == 3:
                raise RuntimeError(
                    f"Upload of {path.name} failed after {attempt} attempts: {error}"
                ) from error
            delay = attempt * 15
            print(
                f"Upload of {path.name} failed on attempt {attempt}; "
                f"retrying in {delay}s: {error}"
            )
            time.sleep(delay)


def upload_order(tag: str, assets: list[Path]) -> list[Path]:
    def rank(path: Path) -> tuple[int, str]:
        name = path.name
        if tag == "aera-latest":
            return (0 if name == "catalog-nightly.json" else 1, name)
        if tag == "aera-plugins-mirror":
            if name not in {"catalog.json", "catalog.json.sig"}:
                return (0, name)
            return (1 if name == "catalog.json.sig" else 2, name)
        if name in {"catalog.json", "catalog-nightly.json"}:
            return (2, name)
        if name == "SHA256SUMS":
            return (1, name)
        return (0, name)

    return sorted(assets, key=rank)


def main() -> None:
    if len(sys.argv) != 7:
        raise SystemExit(
            f"Usage: {sys.argv[0]} <owner/repo> <asset-dir> <tag> "
            "<title> <notes> <target-commitish>"
        )

    repository, directory, tag, title, notes, target_commitish = sys.argv[1:]
    if not REPOSITORY_RE.fullmatch(repository):
        raise SystemExit(f"Invalid Gitee repository: {repository!r}")
    if not TAG_RE.fullmatch(tag):
        raise SystemExit(f"Invalid Gitee release tag: {tag!r}")
    token = os.environ.get("GITEE_TOKEN", "")
    if not token:
        raise SystemExit("GITEE_TOKEN is required to publish a Gitee Release")

    asset_dir = Path(directory)
    assets = sorted(path for path in asset_dir.iterdir() if path.is_file())
    if not assets:
        raise SystemExit(f"No release assets found in {asset_dir}")

    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "AERA-infiniti-Gitee-release-publisher/1",
        }
    )

    release_id = ensure_release(
        session, repository, tag, title, notes, target_commitish
    )
    desired_names = {path.name for path in assets}
    attachments = list_attachments(session, repository, release_id)
    for attachment in attachments:
        attachment_id = attachment.get("id")
        if not attachment_id:
            raise RuntimeError("Gitee returned an attachment without an ID")
        # Re-uploading the same names makes reruns idempotent and prunes stale
        # plugin assets whose signed catalog entry has been removed upstream.
        delete_url = (
            f"{API_ROOT}/repos/{repository}/releases/{release_id}/"
            f"attach_files/{attachment_id}"
        )
        request(session, "DELETE", delete_url)

    for path in upload_order(tag, assets):
        result = upload_attachment(session, repository, release_id, path)
        download_url = result.get("browser_download_url", "")
        expected_url = f"{GITEE_ROOT}/{repository}/releases/download/{tag}/{path.name}"
        if download_url and download_url != expected_url:
            raise RuntimeError(
                f"Gitee returned an unexpected download URL for {path.name}: "
                f"{download_url}"
            )
        print(f"Uploaded {path.name} ({path.stat().st_size} bytes) to {tag}")

    release = get_release(session, repository, tag)
    if release is None:
        raise RuntimeError(f"Gitee release {tag} disappeared after upload")
    published = {asset.get("name"): asset.get("browser_download_url")
                 for asset in release.get("assets", [])}
    missing = desired_names.difference(published)
    if missing:
        raise RuntimeError(
            "Gitee release is missing uploaded assets: " + ", ".join(sorted(missing))
        )
    for name in desired_names:
        expected_url = f"{GITEE_ROOT}/{repository}/releases/download/{tag}/{name}"
        if published[name] != expected_url:
            raise RuntimeError(
                f"Gitee download URL mismatch for {name}: {published[name]}"
            )

    print(
        f"Published {len(desired_names)} assets to "
        f"https://gitee.com/{repository}/releases/tag/{tag}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Gitee release publishing failed: {error}", file=sys.stderr)
        raise SystemExit(1)
