#!/usr/bin/env python3
"""Promote farm auto-captures into sources/our_cs2 (YOLO) with quality gates.

Reads:
  data/captures/<pc>/<session>/{images,meta,labels_soft}

Writes accepted pairs into:
  yolov8/datasets/sources/our_cs2/{train,val,test}/{images,labels}

No human labeling — uses soft labels from capture + optional re-threshold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
CLASS_NAMES = ("c", "ch", "t", "th")


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_label_boxes(path: Path) -> list[tuple[int, float, float, float, float]]:
    out: list[tuple[int, float, float, float, float]] = []
    if not path.is_file():
        return out
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split()
        if len(parts) != 5:
            continue
        cls = int(float(parts[0]))
        vals = [float(x) for x in parts[1:]]
        if cls < 0 or cls > 3:
            continue
        if any(v < -0.01 or v > 1.01 for v in vals):
            continue
        out.append((cls, *vals))  # type: ignore[misc]
    return out


def filter_labels_by_conf_meta(
    boxes: list[tuple[int, float, float, float, float]],
    meta: dict,
    *,
    min_conf: dict[int, float],
) -> list[tuple[int, float, float, float, float]]:
    """If meta has detection confs, drop soft boxes below per-class min."""
    det_conf: dict[int, list[float]] = {i: [] for i in range(4)}
    for d in meta.get("detections") or []:
        name = str(d.get("cls", ""))
        if name not in CLASS_NAMES:
            continue
        det_conf[CLASS_NAMES.index(name)].append(float(d.get("conf", 0.0)))
    if not any(det_conf.values()):
        return boxes
    kept: list[tuple[int, float, float, float, float]] = []
    for box in boxes:
        cls = box[0]
        confs = det_conf.get(cls) or []
        best = max(confs) if confs else 0.0
        if best >= min_conf.get(cls, 0.5):
            kept.append(box)
    return kept


def write_label(path: Path, boxes: list[tuple[int, float, float, float, float]]) -> None:
    lines = [
        f"{cls} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}" for cls, cx, cy, w, h in boxes
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def iter_capture_pairs(raw_root: Path) -> list[tuple[Path, Path, Path | None]]:
    """Return list of (image, label_soft|empty, meta|None)."""
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Promote auto-captures → our_cs2")
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("data/captures"),
        help="Farm captures root (relative to csgobot cwd or absolute)",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=Path("yolov8/datasets/sources/our_cs2"),
        help="YOLO our_cs2 root",
    )
    parser.add_argument("--train-pct", type=int, default=80)
    parser.add_argument("--val-pct", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--copy-images", action="store_true", default=True)
    parser.add_argument("--allow-empty", action="store_true", help="Keep empty labels")
    parser.add_argument("--max-empty-pct", type=float, default=8.0)
    parser.add_argument("--min-ct-share", type=float, default=0.50)
    parser.add_argument("--prefer-team-t", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    # Resolve relative to csgobot root when invoked from repo root.
    cwd = Path.cwd()
    raw_root = args.raw_root
    out_root = args.out_root
    if not raw_root.is_absolute():
        cand = cwd / "vendor" / "csgobot" / raw_root
        raw_root = cand if cand.exists() else (cwd / raw_root)
    if not out_root.is_absolute():
        cand = cwd / "vendor" / "csgobot" / out_root
        if (cwd / "vendor" / "csgobot").is_dir():
            out_root = cand
        else:
            out_root = cwd / out_root

    pairs = iter_capture_pairs(raw_root)
    print(f"raw pairs found: {len(pairs)} under {raw_root}")
    if not pairs:
        print("ERROR: no captures found. Enable CSGOBOT_AUTO_CAPTURE=1 on a collector PC.")
        return 1

    min_conf = {0: 0.35, 1: 0.38, 2: 0.50, 3: 0.50}
    accepted: list[tuple[Path, list, dict, float]] = []
    # (image, boxes, meta, priority)
    seen_hash: set[str] = set()

    for img, label_path, meta_path in pairs:
        digest = sha1_file(img)
        if digest in seen_hash:
            continue
        seen_hash.add(digest)
        meta: dict = {}
        if meta_path is not None:
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        boxes = parse_label_boxes(label_path)
        boxes = filter_labels_by_conf_meta(boxes, meta, min_conf=min_conf)
        if not boxes and not args.allow_empty:
            # Keep a small fraction of negatives later via max_empty_pct only if allow_empty
            continue
        priority = 1.0
        team = str(meta.get("team", "")).lower()
        trigger = str(meta.get("trigger", ""))
        if args.prefer_team_t and team == "t":
            priority += 1.5
        if trigger in ("soft_ct", "roi_miss", "timer_t"):
            priority += 1.0
        cls_counts = Counter(b[0] for b in boxes)
        ct = cls_counts[0] + cls_counts[1]
        if ct > 0:
            priority += 1.0
        accepted.append((img, boxes, meta, priority))

    if not accepted:
        print("ERROR: nothing accepted after filters (labels too weak / empty).")
        print("  Tip: run more sessions as T, or lower label conf during capture.")
        return 1

    # Prefer CT-heavy / team-T samples when trimming for balance messaging
    accepted.sort(key=lambda x: (-x[3], x[0].name))

    # Optional empty quota
    with_boxes = [a for a in accepted if a[1]]
    empties = [a for a in accepted if not a[1]]
    max_empty = int(len(with_boxes) * (args.max_empty_pct / 100.0)) if args.allow_empty else 0
    selected = list(with_boxes)
    if max_empty > 0 and empties:
        selected.extend(empties[:max_empty])

    box_counts = Counter()
    for _, boxes, _, _ in selected:
        for b in boxes:
            box_counts[b[0]] += 1
    total_boxes = sum(box_counts.values()) or 1
    ct_share = (box_counts[0] + box_counts[1]) / total_boxes
    print(
        f"accepted={len(selected)} boxes={total_boxes} "
        f"ct_share={ct_share:.1%} "
        f"(c={box_counts[0]} ch={box_counts[1]} t={box_counts[2]} th={box_counts[3]})"
    )
    if ct_share < args.min_ct_share:
        print(
            f"WARN: CT share {ct_share:.1%} < target {args.min_ct_share:.0%}. "
            "Collect more team=T / soft_ct frames before next train."
        )

    rng = random.Random(args.seed)
    order = list(selected)
    rng.shuffle(order)
    n = len(order)
    n_train = max(1, int(n * args.train_pct / 100.0))
    n_val = max(1, int(n * args.val_pct / 100.0)) if n >= 10 else max(0, n - n_train)
    if n_train + n_val > n:
        n_val = max(0, n - n_train)
    n_test = n - n_train - n_val
    splits = {
        "train": order[:n_train],
        "val": order[n_train : n_train + n_val],
        "test": order[n_train + n_val :],
    }
    print(f"split: train={len(splits['train'])} val={len(splits['val'])} test={len(splits['test'])}")

    if args.dry_run:
        print("dry-run: not writing files")
        return 0

    for split, items in splits.items():
        img_dir = out_root / split / "images"
        lbl_dir = out_root / split / "labels"
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)
        for img, boxes, meta, _ in items:
            stem = f"cap_{meta.get('pc_id', 'pc')}_{img.stem}"
            stem = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in stem)[:180]
            dst_img = img_dir / f"{stem}{img.suffix.lower()}"
            dst_lbl = lbl_dir / f"{stem}.txt"
            if dst_img.exists():
                continue
            shutil.copy2(img, dst_img)
            write_label(dst_lbl, boxes)

    print(f"OK: promoted into {out_root}")
    print("Next: rebuild product dataset (merge our_cs2) then TrainProductModel.bat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
