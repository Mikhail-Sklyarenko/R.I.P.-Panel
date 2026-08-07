#!/usr/bin/env python3
"""Import empty-label YOLO frames into sources/hard_negatives.

Use when you already have a YOLO dataset (e.g. product_v1_bootstrap) that
includes empty map frames. Those frames teach the detector that crates/walls
are not players — do not delete them; stage them as hard negatives.

Preserves train/val/test membership from the source (no cross-split leakage).
Always writes empty label files (never copies non-empty boxes).

Examples:
  # Parent containing train|val|test (USB dump or product_v1_bootstrap):
  python import_empty_yolo_splits.py \\
    --dataset-root "/Volumes/NO NAME" \\
    --out-root yolov8/datasets/sources/hard_negatives

  # Explicit split roots:
  python import_empty_yolo_splits.py \\
    --split train=/data/product_v1_bootstrap/train \\
    --split val=/data/product_v1_bootstrap/val \\
    --out-root yolov8/datasets/sources/hard_negatives
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SPLITS = ("train", "val", "test")


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_csgobot_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    cwd = Path.cwd()
    parts = path.parts
    # Already repo-relative (vendor/csgobot/...)
    if len(parts) >= 2 and parts[0] == "vendor" and parts[1] == "csgobot":
        return cwd / path
    csgobot = cwd / "vendor" / "csgobot"
    if csgobot.is_dir():
        return csgobot / path
    # Running from inside vendor/csgobot
    if cwd.name == "csgobot" and (cwd / "yolov8").is_dir():
        return cwd / path
    return cwd / path


def is_empty_label(label_path: Path) -> bool:
    if not label_path.is_file():
        return False
    text = label_path.read_text(encoding="utf-8", errors="ignore")
    return not any(ln.strip() for ln in text.splitlines())


def discover_splits(dataset_root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for split in SPLITS:
        split_dir = dataset_root / split
        if (split_dir / "images").is_dir() and (split_dir / "labels").is_dir():
            found[split] = split_dir
    return found


def iter_empty_pairs(split_dir: Path) -> list[tuple[Path, Path]]:
    images_dir = split_dir / "images"
    labels_dir = split_dir / "labels"
    labels = {p.stem: p for p in labels_dir.iterdir() if p.suffix.lower() == ".txt"}
    out: list[tuple[Path, Path]] = []
    for img in images_dir.iterdir():
        if not img.is_file() or img.suffix.lower() not in IMAGE_EXTS:
            continue
        lbl = labels.get(img.stem)
        if lbl is None:
            continue
        if is_empty_label(lbl):
            out.append((img, lbl))
    return sorted(out, key=lambda t: t[0].name)


def safe_stem(stem: str, *, prefix: str) -> str:
    raw = f"{prefix}{stem}" if prefix else stem
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in raw)
    return cleaned[:180] or "hn_empty"


def import_empties(
    splits: dict[str, Path],
    out_root: Path,
    *,
    prefix: str,
    dry_run: bool,
    max_per_split: int,
) -> dict:
    counts = {s: 0 for s in SPLITS}
    skipped_dup = 0
    skipped_exists = 0
    seen_hashes: set[str] = set()
    rows: list[dict] = []

    for split, split_dir in splits.items():
        pairs = iter_empty_pairs(split_dir)
        if max_per_split > 0:
            pairs = pairs[:max_per_split]
        out_img = out_root / split / "images"
        out_lbl = out_root / split / "labels"
        if not dry_run:
            out_img.mkdir(parents=True, exist_ok=True)
            out_lbl.mkdir(parents=True, exist_ok=True)

        for img, _lbl in pairs:
            digest = sha1_file(img)
            if digest in seen_hashes:
                skipped_dup += 1
                continue
            seen_hashes.add(digest)
            stem = safe_stem(img.stem, prefix=prefix)
            dst_img = out_img / f"{stem}{img.suffix.lower()}"
            dst_lbl = out_lbl / f"{stem}.txt"
            if dst_img.exists() or dst_lbl.exists():
                skipped_exists += 1
                continue
            if not dry_run:
                shutil.copy2(img, dst_img)
                # Always empty — never reinforce any accidental boxes.
                dst_lbl.write_text("", encoding="utf-8")
            counts[split] += 1
            rows.append(
                {
                    "split": split,
                    "stem": stem,
                    "src": str(img),
                    "sha1": digest,
                }
            )

    total = sum(counts.values())
    return {
        "counts": counts,
        "total": total,
        "skipped_dup": skipped_dup,
        "skipped_exists": skipped_exists,
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import empty YOLO labels → sources/hard_negatives"
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=None,
        help="Parent with train/val/test YOLO splits (e.g. product_v1_bootstrap)",
    )
    parser.add_argument(
        "--split",
        action="append",
        default=[],
        help="Explicit split=path (repeatable), e.g. train=/data/.../train",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=Path("yolov8/datasets/sources/hard_negatives"),
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="hn_bs_",
        help="Filename prefix to avoid stem collisions with other sources",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-per-split", type=int, default=0)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Write full JSON manifest (default: <out-root>/manifest.json)",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="Write slim summary JSON (counts only)",
    )
    args = parser.parse_args(argv)

    splits: dict[str, Path] = {}
    if args.dataset_root is not None:
        root = args.dataset_root
        if not root.is_absolute():
            root = resolve_csgobot_path(root)
        found = discover_splits(root)
        if not found:
            print(f"ERROR: no train/val/test YOLO splits under {root}")
            return 1
        splits.update(found)

    for raw in args.split:
        if "=" not in raw:
            print(f"ERROR: invalid --split {raw!r}, expected split=path")
            return 1
        name, path_s = raw.split("=", 1)
        name = name.strip().lower()
        if name not in SPLITS:
            print(f"ERROR: unknown split {name!r}")
            return 1
        p = Path(path_s)
        if not p.is_absolute():
            p = resolve_csgobot_path(p)
        splits[name] = p

    if not splits:
        print("ERROR: provide --dataset-root and/or --split")
        return 1

    out_root = resolve_csgobot_path(args.out_root)
    print(f"out-root: {out_root}")
    for split, path in sorted(splits.items()):
        print(f"  source {split}: {path}")

    result = import_empties(
        splits,
        out_root,
        prefix=args.prefix,
        dry_run=args.dry_run,
        max_per_split=args.max_per_split,
    )

    print(
        f"{'DRY-RUN ' if args.dry_run else ''}OK: staged {result['total']} empty frames "
        f"(train={result['counts']['train']} val={result['counts']['val']} "
        f"test={result['counts']['test']}; "
        f"dup={result['skipped_dup']} exists={result['skipped_exists']})"
    )

    if result["total"] == 0:
        print("ERROR: no empty-label images found")
        return 2

    if args.dry_run:
        return 0

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "tool": "import_empty_yolo_splits.py",
        "purpose": "hard_negatives from empty YOLO labels (texture FP fix)",
        "prefix": args.prefix,
        "sources": {k: str(v) for k, v in sorted(splits.items())},
        "counts": result["counts"],
        "total": result["total"],
        "skipped_dup": result["skipped_dup"],
        "skipped_exists": result["skipped_exists"],
        "samples": result["rows"],
    }
    manifest_path = args.manifest or (out_root / "manifest.json")
    if not manifest_path.is_absolute():
        manifest_path = resolve_csgobot_path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    # Full manifest can be large; still useful on TRAIN disk.
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"manifest: {manifest_path}")

    summary = {
        "created_utc": manifest["created_utc"],
        "tool": manifest["tool"],
        "purpose": manifest["purpose"],
        "prefix": args.prefix,
        "sources": manifest["sources"],
        "counts": result["counts"],
        "total": result["total"],
        "skipped_dup": result["skipped_dup"],
        "skipped_exists": result["skipped_exists"],
    }
    if args.summary is not None:
        summary_path = args.summary
        if not summary_path.is_absolute():
            summary_path = resolve_csgobot_path(summary_path)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"summary: {summary_path}")

    print("Next: merge --source hn=.../hard_negatives into product, then TrainProductModel.bat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
