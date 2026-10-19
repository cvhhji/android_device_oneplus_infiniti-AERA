#!/usr/bin/env python3
"""Mirror signed AERA plugin packages to deterministic GitHub Release assets."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


CATALOG_URL = "https://raw.githubusercontent.com/AERA-Plugins/registry/main/catalog.json"
SIGNATURE_URL = CATALOG_URL + ".sig"
PUBLIC_KEY = bytes.fromhex(
    "16ee367dd2d7ae19a0d162fb7166e0f7"
    "692de0ed28794d445eedad086e4873e9"
)
MAX_CATALOG = 1024 * 1024
MAX_SIGNATURE = 4096
MAX_PACKAGE = 513 * 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024 * 1024
OFFICIAL_HOSTS = {"raw.githubusercontent.com", "github.com"}


def official_url(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 2048:
        return False
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_HOSTS:
        return False
    if parsed.username or parsed.password or not parsed.path:
        return False
    if parsed.hostname == "raw.githubusercontent.com":
        return parsed.path.startswith("/AERA-Plugins/")
    return parsed.path.startswith("/AERA-Plugins/")


def download(url: str, path: Path, limit: int, expected_size: int = 0,
             expected_hash: str = "") -> int:
    if not official_url(url):
        raise RuntimeError(f"Refusing non-official AERA URL: {url}")
    request = Request(url, headers={"User-Agent": "AERA-infiniti-plugin-mirror/1"})
    digest = hashlib.sha256()
    total = 0
    with urlopen(request, timeout=180) as response, path.open("wb") as output:
        declared_size = response.headers.get("Content-Length")
        if declared_size and int(declared_size) > limit:
            raise RuntimeError(f"Remote file exceeds size limit: {url}")
        if expected_size and declared_size and int(declared_size) != expected_size:
            raise RuntimeError(f"Remote size differs from signed catalog: {url}")
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > limit:
                raise RuntimeError(f"Remote file exceeds size limit: {url}")
            digest.update(block)
            output.write(block)
    if expected_size and total != expected_size:
        raise RuntimeError(f"Downloaded size differs from signed catalog: {url}")
    if expected_hash and digest.hexdigest().lower() != expected_hash.lower():
        raise RuntimeError(f"SHA-256 differs from signed catalog: {url}")
    return total


def asset_name(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--keep-file", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    catalog_path = args.output / "catalog.json"
    signature_path = args.output / "catalog.json.sig"
    download(CATALOG_URL, catalog_path, MAX_CATALOG)
    download(SIGNATURE_URL, signature_path, MAX_SIGNATURE)
    catalog_bytes = catalog_path.read_bytes()
    signature_text = signature_path.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{128}", signature_text):
        raise RuntimeError("AERA catalog signature is malformed")
    Ed25519PublicKey.from_public_bytes(PUBLIC_KEY).verify(
        bytes.fromhex(signature_text), catalog_bytes
    )

    catalog = json.loads(catalog_bytes)
    if not isinstance(catalog, dict) or catalog.get("schema") != 1:
        raise RuntimeError("AERA plugin catalog schema is unsupported")
    plugins = catalog.get("plugins")
    if not isinstance(plugins, list) or len(plugins) > 64:
        raise RuntimeError("AERA plugin catalog schema is unsupported")

    packages: dict[str, tuple[int, str]] = {}
    for plugin in plugins:
        if not isinstance(plugin, dict):
            raise RuntimeError("AERA plugin catalog contains a malformed entry")
        url = plugin.get("package_url")
        size = plugin.get("package_size")
        digest = plugin.get("package_sha256")
        if (not official_url(url) or not isinstance(size, int) or
                size <= 0 or size > MAX_PACKAGE or
                not isinstance(digest, str) or
                not re.fullmatch(r"[0-9a-fA-F]{64}", digest)):
            raise RuntimeError(f"AERA plugin package metadata is invalid: {plugin.get('id')}")
        metadata = (size, digest.lower())
        previous = packages.setdefault(url, metadata)
        if previous != metadata:
            raise RuntimeError(f"Conflicting signed metadata for plugin package: {url}")

    total = catalog_path.stat().st_size + signature_path.stat().st_size
    for url, (size, digest) in packages.items():
        total += size
        if total > MAX_TOTAL:
            raise RuntimeError("AERA plugin mirror exceeds the configured 8 GiB limit")
        destination = args.output / asset_name(url)
        download(url, destination, MAX_PACKAGE, size, digest)

    names = sorted(path.name for path in args.output.iterdir() if path.is_file())
    args.keep_file.write_text("".join(f"{name}\n" for name in names), encoding="utf-8")
    print(f"Verified the signed catalog and mirrored {len(packages)} plugin packages.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"AERA plugin mirror failed: {error}", file=sys.stderr)
        raise SystemExit(1)
