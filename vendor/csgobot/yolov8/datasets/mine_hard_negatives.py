#!/usr/bin/env python3
"""Mine / stage hard negatives for texture FP reduction.

Modes:
  captures  — promote empty_scene / texture_fp / hard_neg captures (no YOLO needed)
  folder    — copy a folder of known-empty screenshots with empty YOLO labels
  predict   — run current weights on a folder; keep images where model fires
              (assumes folder is player-free → those dets are FP → empty labels)

Examples:
  python promote_hard_negatives.py --raw-root data/captures
  python mine_hard_negatives.py --mode folder --images-dir ./fp_dump --out-root ...
  python mine_hard_negatives.py --mode predict --images-dir ./fp_dump --weights ./yolov8/cs2_....pt
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


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
    cand = cwd / "vendor" / "csgobot" / path
    if cand.exists() or (cwd / "vendor" / "csgobot").is_dir():
        # Prefer csgobot-relative when that tree exists
        if (cwd / "vendor" / "csgobot").is_dir():
            return cwd / "vendor" / "csgobot" / path
    return cwd / path


def iter_images(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file() and root.suffix.lower() in IMAGE_EXTS:
        return [root]
    out: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            out.append(p)
    return sorted(out)


def write_empty_pair(img: Path, out_images: Path, out_labels: Path, stem: str) -> bool:
    dst_img = out_images / f"{stem}{img.suffix.lower()}"
    dst_lbl = out_labels / f"{stem}.txt"
    if dst_img.exists():
        return False
    shutil.copy2(img, dst_img)
    dst_lbl.write_text("", encoding="utf-8")
    return True


def mode_folder(images_dir: Path, out_root: Path, *, max_images: int, seed: int) -> int:
    imgs = iter_images(images_dir)
    if not imgs:
        print(f"ERROR: no images under {images_dir}")
        return 1
    if max_images > 0 and len(imgs) > max_images:
        import random

        imgs = random.Random(seed).sample(imgs, max_images)
    train_img = out_root / "train" / "images"
    train_lbl = out_root / "train" / "labels"
    train_img.mkdir(parents=True, exist_ok=True)
    train_lbl.mkdir(parents=True, exist_ok=True)
    n = 0
    seen: set[str] = set()
    for img in imgs:
        digest = sha1_file(img)
        if digest in seen:
            continue
        seen.add(digest)
        stem = f"hn_folder_{img.stem}"[:160]
        stem = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in stem)
        if write_empty_pair(img, train_img, train_lbl, stem):
            n += 1
    print(f"OK: staged {n} empty-label images → {out_root}/train")
    return 0


def mode_predict(
    images_dir: Path,
    out_root: Path,
    weights: Path,
    *,
    conf: float,
    max_images: int,
    device: str,
) -> int:
    try:
        from ultralytics import YOLO
    except ImportError:
        print("ERROR: ultralytics required (csgobot venv)")
        return 1
    imgs = iter_images(images_dir)
    if not imgs:
        print(f"ERROR: no images under {images_dir}")
        return 1
    if not weights.is_file():
        print(f"ERROR: weights not found: {weights}")
        return 1

    model = YOLO(str(weights))
    train_img = out_root / "train" / "images"
    train_lbl = out_root / "train" / "labels"
    train_img.mkdir(parents=True, exist_ok=True)
    train_lbl.mkdir(parents=True, exist_ok=True)

    kept = 0
    scanned = 0
    for img in imgs:
        scanned += 1
        results = model.predict(
            source=str(img),
            conf=conf,
            verbose=False,
            device=device or None,
        )
        n_boxes = 0
        for r in results:
            if r.boxes is not None:
                n_boxes += len(r.boxes)
        if n_boxes < 1:
            continue
        stem = f"hn_fp_{img.stem}"[:160]
        stem = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in stem)
        if write_empty_pair(img, train_img, train_lbl, stem):
            kept += 1
            print(f"  FP mine: {img.name} boxes={n_boxes}")
        if max_images > 0 and kept >= max_images:
            break

    print(f"OK: scanned={scanned} hard-neg(FP)={kept} → {out_root}/train")
    print("Assumes input folder is player-free; model boxes = texture FPs.")
    return 0 if kept else 2


def mode_captures(raw_root: Path, out_root: Path, max_images: int) -> int:
    # Delegate to promote_hard_negatives
    from promote_hard_negatives import main as promote_main

    argv = [
        "--raw-root",
        str(raw_root),
        "--out-root",
        str(out_root),
    ]
    if max_images > 0:
        argv.extend(["--max-images", str(max_images)])
    return int(promote_main(argv))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mine / stage hard negatives")
    parser.add_argument(
        "--mode",
        choices=("captures", "folder", "predict"),
        default="captures",
    )
    parser.add_argument("--raw-root", type=Path, default=Path("data/captures"))
    parser.add_argument("--images-dir", type=Path, default=None)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=Path("yolov8/datasets/sources/hard_negatives"),
    )
    parser.add_argument(
        "--weights",
        type=Path,
        default=Path("yolov8/cs2_yolov8m_640_augmented_v4.pt"),
    )
    parser.add_argument("--conf", type=float, default=0.45)
    parser.add_argument("--device", type=str, default="")
    parser.add_argument("--max-images", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    out_root = resolve_csgobot_path(args.out_root)

    if args.mode == "captures":
        raw = resolve_csgobot_path(args.raw_root)
        # promote resolves its own paths; pass absolute
        return mode_captures(raw, out_root, args.max_images)

    if args.images_dir is None:
        print("ERROR: --images-dir required for folder/predict modes")
        return 1
    images_dir = args.images_dir
    if not images_dir.is_absolute():
        images_dir = resolve_csgobot_path(images_dir)

    if args.mode == "folder":
        return mode_folder(
            images_dir, out_root, max_images=args.max_images, seed=args.seed
        )

    weights = args.weights
    if not weights.is_absolute():
        weights = resolve_csgobot_path(weights)
    return mode_predict(
        images_dir,
        out_root,
        weights,
        conf=args.conf,
        max_images=args.max_images,
        device=args.device,
    )


if __name__ == "__main__":
    # Allow import of sibling promote_hard_negatives when run from datasets/
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    raise SystemExit(main())
