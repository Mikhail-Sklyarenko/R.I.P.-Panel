#!/usr/bin/env python3
"""Prepare a trained .pt for registry promote (prints JSON snippet + optional install)."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "resources" / "csgobot" / "weights_registry.json"
CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hash a trained checkpoint and emit weights_registry artifact snippet."
    )
    parser.add_argument("weights", type=Path, help="path to best.pt / candidate .pt")
    parser.add_argument("--version", type=str, required=True, help="e.g. v0.2.0-ctfix")
    parser.add_argument(
        "--url",
        type=str,
        default="",
        help="public download URL after you host the file (GitHub Release / CDN)",
    )
    parser.add_argument(
        "--dataset-manifest",
        type=str,
        default=None,
        help="relative path to dataset manifest used for this train",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="copy into vendor/csgobot/yolov8/ under filename from --filename",
    )
    parser.add_argument(
        "--filename",
        type=str,
        default=None,
        help="install/runtime filename (default: keep source name)",
    )
    parser.add_argument(
        "--set-active",
        action="store_true",
        help="write artifact into registry and set active (requires --url unless dry)",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY,
    )
    args = parser.parse_args(argv)

    src = args.weights.resolve()
    if not src.is_file():
        print(f"ERROR: not a file: {src}")
        return 1

    filename = args.filename or src.name
    digest = sha256_file(src)
    size = src.stat().st_size
    artifact = {
        "filename": filename,
        "url": args.url or "<HOST_THEN_PASTE_URL>",
        "sha256": digest,
        "size_bytes": size,
        "classes": ["c", "ch", "t", "th"],
        "imgsz": 640,
        "source": "R.I.P. Panel train_product",
        "dataset_manifest": args.dataset_manifest,
        "notes": f"Candidate promote for {args.version}. Soak on 1-2 farm PCs before fleet.",
    }

    print("=== registry artifact snippet ===")
    print(json.dumps({args.version: artifact}, indent=2))
    print()
    print(f"sha256: {digest}")
    print(f"size_bytes: {size}")
    print()
    print("Next:")
    print("  1) Host the .pt (GitHub Release / object storage)")
    print("  2) Put real url into resources/csgobot/weights_registry.json")
    print("  3) Set active to this version")
    print("  4) Farm PCs: git pull && EnsureWeights.bat")

    if args.install:
        dest = REPO_ROOT / "vendor" / "csgobot" / "yolov8" / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        print(f"installed local copy: {dest}")

    if args.set_active:
        if not args.url:
            print("ERROR: --set-active requires --url")
            return 1
        registry = json.loads(args.registry.read_text(encoding="utf-8"))
        registry.setdefault("artifacts", {})[args.version] = artifact
        registry["active"] = args.version
        args.registry.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
        print(f"updated registry: {args.registry} active={args.version}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
