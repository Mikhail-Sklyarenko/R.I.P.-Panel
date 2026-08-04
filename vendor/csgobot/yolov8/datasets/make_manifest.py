"""Create immutable manifest for a built YOLO dataset.

Manifest captures counts + hashes for reproducibility and release tracking.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_label(path: Path) -> Counter:
    c = Counter()
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        c[int(float(ln.split()[0]))] += 1
    return c


def build_manifest(
    root: Path,
    class_names: list[str],
    sources: list[str],
    *,
    include_file_hashes: bool = False,
) -> dict:
    out: dict = {
        "dataset_root": root.name,
        "class_names": class_names,
        "sources": sources,
        "splits": {},
        "totals": {},
    }
    total_images = 0
    total_labels = 0
    total_boxes = 0
    total_counts = Counter()
    label_hashes: dict[str, str] = {}

    for split in ("train", "val", "test"):
        img_dir = root / split / "images"
        lbl_dir = root / split / "labels"
        images = [p for p in img_dir.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS] if img_dir.exists() else []
        labels = [p for p in lbl_dir.rglob("*.txt") if p.is_file()] if lbl_dir.exists() else []

        counts = Counter()
        boxes = 0
        for lp in labels:
            cc = parse_label(lp)
            counts.update(cc)
            boxes += sum(cc.values())
            label_hashes[str(lp.relative_to(root))] = sha256_file(lp)

        split_item = {
            "images": len(images),
            "labels": len(labels),
            "boxes": boxes,
            "class_counts": {str(i): counts[i] for i in range(len(class_names))},
        }
        out["splits"][split] = split_item

        total_images += len(images)
        total_labels += len(labels)
        total_boxes += boxes
        total_counts.update(counts)

    out["totals"] = {
        "images": total_images,
        "labels": total_labels,
        "boxes": total_boxes,
        "class_counts": {str(i): total_counts[i] for i in range(len(class_names))},
    }
    sorted_hashes = dict(sorted(label_hashes.items()))
    out["dataset_hash_sha256"] = hashlib.sha256(
        json.dumps(sorted_hashes, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if include_file_hashes:
        out["label_file_hashes_sha256"] = sorted_hashes
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Create dataset manifest json")
    parser.add_argument("--root", type=Path, required=True, help="YOLO dataset root")
    parser.add_argument("--classes", type=str, default="c,ch,t,th")
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="Optional source provenance notes (can repeat)",
    )
    parser.add_argument("--out", type=Path, required=True, help="Output manifest json path")
    parser.add_argument(
        "--include-file-hashes",
        action="store_true",
        help="Embed per-label sha256 map (large). Default is slim summary + dataset_hash only.",
    )
    args = parser.parse_args()

    class_names = [x.strip() for x in args.classes.split(",") if x.strip()]
    manifest = build_manifest(
        args.root,
        class_names,
        args.source,
        include_file_hashes=args.include_file_hashes,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"manifest written: {args.out}")
    print(f"dataset_hash_sha256: {manifest['dataset_hash_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
