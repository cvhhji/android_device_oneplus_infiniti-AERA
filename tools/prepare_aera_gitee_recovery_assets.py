#!/usr/bin/env python3
"""Split AERA recovery payloads into Gitee-sized parts and prepare catalogs."""

import hashlib
import json
from pathlib import Path
import re
import shutil
import sys


PART_SIZE = 8 * 1024 * 1024
IMAGE_NAME = "AERA-infiniti-aera-17.0-recovery.img"
PACKAGE_NAME = "AERA-infiniti-aera-17.0-recovery.zip"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
TAG_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def split_file(path: Path, output_dir: Path) -> list[dict[str, object]]:
    parts: list[dict[str, object]] = []
    with path.open("rb") as source:
        index = 0
        while block := source.read(PART_SIZE):
            name = f"{path.name}.part{index:03d}"
            destination = output_dir / name
            destination.write_bytes(block)
            parts.append(
                {
                    "filename": name,
                    "size": len(block),
                    "sha256": hashlib.sha256(block).hexdigest(),
                }
            )
            index += 1
    if not parts:
        raise RuntimeError(f"Refusing to publish an empty file: {path}")
    return parts


def clear_output_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for child in directory.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
        else:
            raise RuntimeError(f"Unexpected directory in Gitee asset output: {child}")


def main() -> None:
    if len(sys.argv) != 6:
        raise SystemExit(
            f"Usage: {sys.argv[0]} <release-dir> <gitee-asset-dir> "
            "<gitee-repository> <github-repository> <release-tag>"
        )

    release_dir, asset_dir = Path(sys.argv[1]), Path(sys.argv[2])
    gitee_repository, github_repository, release_tag = sys.argv[3:]
    if not REPOSITORY_RE.fullmatch(gitee_repository):
        raise SystemExit(f"Invalid Gitee repository: {gitee_repository!r}")
    if not REPOSITORY_RE.fullmatch(github_repository):
        raise SystemExit(f"Invalid GitHub repository: {github_repository!r}")
    if not TAG_RE.fullmatch(release_tag):
        raise SystemExit(f"Invalid recovery release tag: {release_tag!r}")

    image_path = release_dir / IMAGE_NAME
    package_path = release_dir / PACKAGE_NAME
    for path in (image_path, package_path):
        if not path.is_file() or path.stat().st_size <= 0:
            raise SystemExit(f"Missing recovery release asset: {path}")

    clear_output_directory(asset_dir)
    image_parts = split_file(image_path, asset_dir)
    package_parts = split_file(package_path, asset_dir)
    gitee_base = (
        f"https://gitee.com/{gitee_repository}/raw/aera-recovery-assets/"
    )
    def gitee_url(name: str) -> str:
        return f"{gitee_base}{name}?build={release_tag}"
    github_package_url = (
        f"https://github.com/{github_repository}/releases/download/"
        f"{release_tag}/{PACKAGE_NAME}"
    )

    def with_urls(parts: list[dict[str, object]]) -> list[dict[str, object]]:
        return [
            {
                "url": gitee_url(str(part["filename"])),
                "size": part["size"],
                "sha256": part["sha256"],
            }
            for part in parts
        ]

    catalog_path = release_dir / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if catalog.get("schema") != 1 or not isinstance(catalog.get("devices"), dict):
        raise RuntimeError("Recovery update catalog has an unsupported schema")
    entry = catalog["devices"].get("infiniti")
    if not isinstance(entry, dict):
        raise RuntimeError("Recovery update catalog does not contain infiniti")

    ota_parts = with_urls(package_parts)
    entry["filename"] = PACKAGE_NAME
    entry["size"] = package_path.stat().st_size
    entry["sha256"] = sha256(package_path)
    entry["ota_url"] = ota_parts[0]["url"]
    entry["fallback_url"] = github_package_url
    entry["ota_parts"] = ota_parts

    encoded_catalog = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    for name in ("catalog.json", "catalog-nightly.json"):
        (release_dir / name).write_text(encoded_catalog, encoding="utf-8")
        shutil.copy2(release_dir / name, asset_dir / name)

    checksums = release_dir / "SHA256SUMS"
    if checksums.is_file():
        shutil.copy2(checksums, asset_dir / checksums.name)

    image_part_urls = [
        gitee_url(str(part["filename"])) for part in image_parts
    ]
    package_part_urls = [part["url"] for part in ota_parts]
    manifest = {
        "schema": 1,
        "build_tag": release_tag,
        "image": {
            "filename": IMAGE_NAME,
            "size": image_path.stat().st_size,
            "sha256": sha256(image_path),
            "parts": [
                {**part, "url": url}
                for part, url in zip(image_parts, image_part_urls, strict=True)
            ],
        },
        "ota_package": {
            "filename": PACKAGE_NAME,
            "size": package_path.stat().st_size,
            "sha256": sha256(package_path),
            "parts": ota_parts,
            "fallback_url": github_package_url,
        },
    }
    (asset_dir / "GITEE-ASSETS.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    image_names = [str(part["filename"]) for part in image_parts]
    package_names = [str(part["filename"]) for part in package_parts]
    image_copy = "+".join(image_names)
    package_copy = "+".join(package_names)
    lines = [
        "AERA Recovery 17.0 Gitee raw downloads",
        "",
        "OTA package (the recovery app downloads and joins these parts automatically):",
        *package_part_urls,
        "",
        "Recovery image parts:",
        *image_part_urls,
        "",
        "To join manually in Windows Command Prompt from the downloaded folder:",
        f"copy /b {image_copy} {IMAGE_NAME}",
        f"copy /b {package_copy} {PACKAGE_NAME}",
        "Verify the joined image and package against SHA256SUMS before flashing.",
    ]
    (asset_dir / "GITEE-DOWNLOADS.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    print(
        f"Prepared {len(image_parts)} recovery-image parts and "
        f"{len(package_parts)} OTA-package parts at {PART_SIZE} bytes each."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Gitee recovery asset preparation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
