#!/usr/bin/env python3
"""Prepare anonymous Gitee downloads without modifying signed plugin packages."""

import argparse
import hashlib
import json
from pathlib import Path
import re


PART_SIZE = 8 * 1024 * 1024
PACKAGE_NAME = re.compile(r"[0-9a-f]{64}")


def prepare(directory: Path) -> list[dict[str, object]]:
    packages = []
    for source in sorted(directory.iterdir()):
        if not source.is_file() or not PACKAGE_NAME.fullmatch(source.name):
            continue
        if source.stat().st_size <= PART_SIZE:
            continue
        parts = []
        with source.open("rb") as stream:
            index = 0
            while block := stream.read(PART_SIZE):
                destination = source.with_name(f"{source.name}.part{index}")
                destination.write_bytes(block)
                parts.append(
                    {
                        "name": destination.name,
                        "size": len(block),
                        "sha256": hashlib.sha256(block).hexdigest(),
                    }
                )
                index += 1
        digest = hashlib.sha256()
        total = 0
        for part in parts:
            content = (directory / str(part["name"])).read_bytes()
            digest.update(content)
            total += len(content)
        original = hashlib.sha256(source.read_bytes()).hexdigest()
        if total != source.stat().st_size or digest.hexdigest() != original:
            raise RuntimeError(f"Multipart reconstruction failed for {source.name}")
        packages.append(
            {
                "name": source.name,
                "size": total,
                "sha256": original,
                "parts": parts,
            }
        )
    return packages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory", nargs="?", type=Path,
        default=Path(__file__).resolve().parent.parent / "vendor/aera-plugins",
    )
    args = parser.parse_args()
    print(json.dumps({"part_size": PART_SIZE, "packages": prepare(args.directory)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
