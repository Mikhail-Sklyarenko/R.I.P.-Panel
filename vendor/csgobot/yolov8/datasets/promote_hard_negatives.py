#!/usr/bin/env python3
"""Promote hard-negative captures into sources/hard_negatives (empty YOLO labels).

Selects frames tagged as texture/empty hard negatives:
  - meta.force_empty == true
  - meta.trigger in empty_scene | texture_fp | hard_neg_timer
  - or --all-empty (any capture with empty soft labels)

Writes:
  yolov8/datasets/sources/hard_negatives/{train,val,test}/{images,labels}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import sys
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
HN_TRIGGERS = frozenset({"empty_scene", "texture_fp", "hard_neg_timer"})


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_capture_pairs(raw_root: Path) -> list[tuple[Path, Path, Path | None]]:
    pairs: list[tuple[Path, Path, Path | None]] = []
    if not raw_root.is_dir():
        return pairs
    for img in raw_root.rglob("*"):
        if not img.is_file() or img.suffix.lower() not in IMAGE_EXTS:
            continue
        if img.parent.name != "images":
            continue
        session = img.parent.parent
        label = session / "labels_soft" / f"{img.stem}.txt"
        meta = session / "meta" / f"{img.stem}.json"
        pairs.append((img, label, meta if meta.is_file() else None))
    return pairs


def label_is_empty(path: Path) -> bool:
    if not path.is_file():
        return True
    text = path.read_text(encoding="utf-8").strip()
    return text == ""


def is_hard_neg(meta: dict, label_path: Path, *, all_empty: bool) -> bool:
    if meta.get("force_empty") is True:
        return True
    if meta.get("hard_neg_mode") is True:
        return True
    trigger = str(meta.get("trigger", ""))
    if trigger in HN_TRIGGERS:
        return True
    if all_empty and label_is_empty(label_path):
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Promote hard-negative captures → sources/hard_negatives"
    )
    parser.add_argument("--raw-root", type=Path, default=Path("data/captures"))
    parser.add_argument(
        "--out-root",
        type=Path,
        default=Path("yolov8/datasets/sources/hard_negatives"),
    )
    parser.add_argument("--train-pct", type=int, default=85)
    parser.add_argument("--val-pct", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-images", type=int, default=0, help="0 = no limit")
    parser.add_argument(
        "--all-empty",
        action="store_true",
        help="Also accept any capture with empty soft labels",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    cwd = Path.cwd()
    raw_root = args.raw_root
    out_root = args.out_root
    if not raw_root.is_absolute():
        cand = cwd / "vendor" / "csgobot" / raw_root
        raw_root = cand if cand.exists() else (cwd / raw_root)
    if not out_root.is_absolute():
        if (cwd / "vendor" / "csgobot").is_dir():
            out_root = cwd / "vendor" / "csgobot" / out_root
        else:
            out_root = cwd / out_root

    pairs = iter_capture_pairs(raw_root)
    print(f"raw pairs found: {len(pairs)} under {raw_root}")
    if not pairs:
        print("ERROR: no captures. Run EnableHardNegCapture.bat / empty_scene sessions.")
        return 1

    accepted: list[tuple[Path, dict]] = []
    seen: set[str] = set()
    for img, label_path, meta_path in pairs:
        digest = sha1_file(img)
        if digest in seen:
            continue
        seen.add(digest)
        meta: dict = {}
        if meta_path is not None:
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        if not is_hard_neg(meta, label_path, all_empty=args.all_empty):
            continue
        accepted.append((img, meta))

    print(f"hard-neg candidates: {len(accepted)}")
    if not accepted:
        print("ERROR: no hard-neg frames. Enable CSGOBOT_CAPTURE_HARD_NEG=1 or wait for empty_scene.")
        return 1

    if args.max_images > 0 and len(accepted) > args.max_images:
        rng = random.Random(args.seed)
        accepted = rng.sample(accepted, args.max_images)
        print(f"trimmed to max_images={args.max_images}")

    rng = random.Random(args.seed)
    order = list(accepted)
    rng.shuffle(order)
    n = len(order)
    n_train = max(1, int(n * args.train_pct / 100.0))
    n_val = max(1, int(n * args.val_pct / 100.0)) if n >= 10 else max(0, n - n_train)
    if n_train + n_val > n:
        n_val = max(0, n - n_train)
    splits = {
        "train": order[:n_train],
        "val": order[n_train : n_train + n_val],
        "test": order[n_train + n_val :],
    }
    print(
        f"split: train={len(splits['train'])} val={len(splits['val'])} "
        f"test={len(splits['test'])} (all empty labels)"
    )

    if args.dry_run:
        print("dry-run: not writing files")
        return 0

    for split, items in splits.items():
        img_dir = out_root / split / "images"
        lbl_dir = out_root / split / "labels"
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)
        for img, meta in items:
            stem = f"hn_{meta.get('pc_id', 'pc')}_{img.stem}"
            stem = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in stem)[:180]
            dst_img = img_dir / f"{stem}{img.suffix.lower()}"
            dst_lbl = lbl_dir / f"{stem}.txt"
            if dst_img.exists():
                continue
            shutil.copy2(img, dst_img)
            dst_lbl.write_text("", encoding="utf-8")

    print(f"OK: hard negatives → {out_root}")
    print("Next: merge --source hn=...hard_negatives into product, then TrainProductModel.bat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
