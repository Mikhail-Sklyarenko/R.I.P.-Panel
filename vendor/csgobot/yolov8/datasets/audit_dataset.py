"""Audit YOLO-format dataset quality and class balance.

Usage:
  python audit_dataset.py --root ../prepared --names c,ch,t,th

Expected structure:
  <root>/<split>/images/*
  <root>/<split>/labels/*.txt
where split is usually train/val/test.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _iter_pairs(split_dir: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    images_dir = split_dir / "images"
    labels_dir = split_dir / "labels"
    images: dict[str, Path] = {}
    labels: dict[str, Path] = {}

    if images_dir.exists():
        for p in images_dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                images[p.stem] = p
    if labels_dir.exists():
        for p in labels_dir.rglob("*.txt"):
            if p.is_file():
                labels[p.stem] = p
    return images, labels


def _parse_yolo_label(path: Path) -> list[tuple[int, float, float, float, float]]:
    rows: list[tuple[int, float, float, float, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            raise ValueError(f"bad token count in {path}: {line}")
        cls = int(float(parts[0]))
        x, y, w, h = (float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]))
        rows.append((cls, x, y, w, h))
    return rows


def _valid_bbox(x: float, y: float, w: float, h: float) -> bool:
    eps = 1e-6
    if w <= 0 or h <= 0:
        return False
    if not (-eps <= x <= 1 + eps and -eps <= y <= 1 + eps):
        return False
    if w > 1 + eps or h > 1 + eps:
        return False
    left = x - w / 2
    right = x + w / 2
    top = y - h / 2
    bottom = y + h / 2
    return left >= -eps and right <= 1 + eps and top >= -eps and bottom <= 1 + eps


def audit(root: Path, names: list[str]) -> int:
    splits = [p for p in root.iterdir() if p.is_dir()]
    if not splits:
        print(f"[error] no split directories under: {root}")
        return 2

    global_counts = Counter()
    global_stats = defaultdict(int)
    bad_files: list[str] = []

    for split in sorted(splits, key=lambda p: p.name):
        images, labels = _iter_pairs(split)
        common = sorted(set(images) & set(labels))
        missing_labels = sorted(set(images) - set(labels))
        missing_images = sorted(set(labels) - set(images))

        stats = defaultdict(int)
        counts = Counter()

        stats["images"] = len(images)
        stats["labels"] = len(labels)
        stats["paired"] = len(common)
        stats["missing_labels"] = len(missing_labels)
        stats["missing_images"] = len(missing_images)

        for stem in common:
            label_path = labels[stem]
            try:
                rows = _parse_yolo_label(label_path)
            except Exception as exc:  # noqa: BLE001
                bad_files.append(f"{label_path}: {exc}")
                stats["parse_errors"] += 1
                continue
            if not rows:
                stats["empty_labels"] += 1
            for cls, x, y, w, h in rows:
                stats["boxes"] += 1
                counts[cls] += 1
                if cls < 0 or cls >= len(names):
                    stats["class_oob"] += 1
                if not _valid_bbox(x, y, w, h):
                    stats["bbox_invalid"] += 1

        print(f"\n## split={split.name}")
        print(
            f"images={stats['images']} labels={stats['labels']} paired={stats['paired']} "
            f"missing_labels={stats['missing_labels']} missing_images={stats['missing_images']}"
        )
        print(
            f"boxes={stats['boxes']} parse_errors={stats['parse_errors']} "
            f"empty_labels={stats['empty_labels']} class_oob={stats['class_oob']} "
            f"bbox_invalid={stats['bbox_invalid']}"
        )

        if stats["boxes"] > 0:
            print("class distribution:")
            for idx, name in enumerate(names):
                c = counts[idx]
                pct = c / stats["boxes"] * 100.0
                print(f"  - {idx}:{name} -> {c} ({pct:.2f}%)")

        global_counts.update(counts)
        for k, v in stats.items():
            global_stats[k] += v

    print("\n## total")
    print(
        f"images={global_stats['images']} labels={global_stats['labels']} paired={global_stats['paired']} "
        f"missing_labels={global_stats['missing_labels']} missing_images={global_stats['missing_images']}"
    )
    print(
        f"boxes={global_stats['boxes']} parse_errors={global_stats['parse_errors']} "
        f"empty_labels={global_stats['empty_labels']} class_oob={global_stats['class_oob']} "
        f"bbox_invalid={global_stats['bbox_invalid']}"
    )
    if global_stats["boxes"] > 0:
        print("class distribution:")
        for idx, name in enumerate(names):
            c = global_counts[idx]
            pct = c / global_stats["boxes"] * 100.0
            print(f"  - {idx}:{name} -> {c} ({pct:.2f}%)")

    if bad_files:
        print("\n## parse errors (first 20)")
        for item in bad_files[:20]:
            print(f"- {item}")

    # non-zero if critical quality errors exist
    critical = (
        global_stats["parse_errors"]
        + global_stats["class_oob"]
        + global_stats["bbox_invalid"]
        + global_stats["missing_labels"]
        + global_stats["missing_images"]
    )
    return 1 if critical else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit YOLO dataset quality")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "prepared",
        help="dataset root containing split folders",
    )
    parser.add_argument(
        "--names",
        type=str,
        default="c,ch,t,th",
        help="comma-separated class names by class id",
    )
    args = parser.parse_args()
    names = [x.strip() for x in args.names.split(",") if x.strip()]
    if not names:
        print("[error] no class names provided")
        return 2
    if not args.root.exists():
        print(f"[error] dataset root does not exist: {args.root}")
        return 2
    return audit(args.root, names)


if __name__ == "__main__":
    raise SystemExit(main())
