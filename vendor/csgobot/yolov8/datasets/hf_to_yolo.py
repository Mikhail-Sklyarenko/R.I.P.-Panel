"""Convert Hugging Face imagefolder dataset to YOLO labels.

Expected HF layout per split:
  <hf_root>/<split>/images/*
  <hf_root>/<split>/metadata.jsonl

`metadata.jsonl` lines are expected to contain:
  - file_name (or image path-like field)
  - objects.bbox as COCO [x, y, w, h] absolute pixels
  - objects.categories as class ids (same length as bbox)

Output:
  <out_root>/<split>/images/*
  <out_root>/<split>/labels/*.txt
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _resolve_image_path(split_dir: Path, item: dict) -> Path:
    # Most HF imagefolder exports use "file_name".
    raw = item.get("file_name") or item.get("image") or item.get("path")
    if isinstance(raw, dict):
        raw = raw.get("path") or raw.get("bytes")
    if not raw:
        raise ValueError("missing image path field")
    p = Path(str(raw))
    if p.is_absolute():
        return p
    # metadata usually references path from split root
    candidate = split_dir / p
    if candidate.exists():
        return candidate
    # fallback to split root by basename
    root_name = split_dir / p.name
    if root_name.exists():
        return root_name
    # fallback to images/<name>
    fallback = split_dir / "images" / p.name
    if fallback.exists():
        return fallback
    raise FileNotFoundError(f"cannot resolve image path: {raw}")


def _to_yolo_line(
    cls_id: int, bbox: list[float], width: int, height: int
) -> str | None:
    if len(bbox) != 4:
        return None
    x, y, w, h = bbox
    if width <= 0 or height <= 0 or w <= 0 or h <= 0:
        return None
    # Clip to image bounds to handle annotation edge spillover.
    x1 = max(0.0, min(float(width), x))
    y1 = max(0.0, min(float(height), y))
    x2 = max(0.0, min(float(width), x + w))
    y2 = max(0.0, min(float(height), y + h))
    w = x2 - x1
    h = y2 - y1
    if w <= 0 or h <= 0:
        return None
    x = x1
    y = y1
    xc = (x + w / 2.0) / width
    yc = (y + h / 2.0) / height
    wn = w / width
    hn = h / height
    # Keep only sane normalized boxes.
    if not (0 <= xc <= 1 and 0 <= yc <= 1 and 0 < wn <= 1 and 0 < hn <= 1):
        return None
    # Numerical stability on boundaries.
    eps = 1e-9
    wn = min(1.0, max(eps, wn))
    hn = min(1.0, max(eps, hn))
    xc = min(1.0 - wn / 2.0, max(wn / 2.0, xc))
    yc = min(1.0 - hn / 2.0, max(hn / 2.0, yc))
    return f"{cls_id} {xc:.6f} {yc:.6f} {wn:.6f} {hn:.6f}"


def _extract_dims(item: dict) -> tuple[int, int]:
    # Common keys in HF metadata exports
    for wk, hk in (
        ("width", "height"),
        ("image_width", "image_height"),
    ):
        if wk in item and hk in item:
            return int(item[wk]), int(item[hk])
    img = item.get("image")
    if isinstance(img, dict):
        if "width" in img and "height" in img:
            return int(img["width"]), int(img["height"])
    # Some CS2 datasets are fixed 640x640 and omit width/height in metadata.
    return 640, 640


def _map_class_id(raw_cls: int) -> int | None:
    # Common public CS2 schema: 0:none, 1:ct_body, 2:ct_head, 3:t_body, 4:t_head
    # Our schema: 0:c, 1:ch, 2:t, 3:th
    if raw_cls == 0:
        return None
    mapped = raw_cls - 1
    if 0 <= mapped <= 3:
        return mapped
    return None


def _link_or_copy(src: Path, dst: Path, link_images: bool) -> None:
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    if link_images:
        dst.symlink_to(src.resolve())
    else:
        shutil.copy2(src, dst)


def convert_split(split_dir: Path, out_dir: Path, *, link_images: bool) -> dict[str, int]:
    images_out = out_dir / "images"
    labels_out = out_dir / "labels"
    images_out.mkdir(parents=True, exist_ok=True)
    labels_out.mkdir(parents=True, exist_ok=True)

    meta = split_dir / "metadata.jsonl"
    if not meta.exists():
        raise FileNotFoundError(f"metadata missing: {meta}")

    stats = {
        "rows": 0,
        "images_copied": 0,
        "labels_written": 0,
        "boxes_written": 0,
        "rows_skipped": 0,
        "boxes_skipped": 0,
    }

    for line in meta.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        stats["rows"] += 1
        try:
            item = json.loads(line)
            img_path = _resolve_image_path(split_dir, item)
            width, height = _extract_dims(item)
            objects = item.get("objects", {})
            boxes = objects.get("bbox", [])
            classes = objects.get("categories", [])
            if len(boxes) != len(classes):
                stats["rows_skipped"] += 1
                continue
        except Exception:
            stats["rows_skipped"] += 1
            continue

        stem = img_path.stem
        img_dest = images_out / f"{stem}{img_path.suffix.lower()}"
        lbl_dest = labels_out / f"{stem}.txt"
        _link_or_copy(img_path, img_dest, link_images=link_images)
        stats["images_copied"] += 1

        yolo_lines: list[str] = []
        for cls_id, bbox in zip(classes, boxes):
            try:
                mapped_cls = _map_class_id(int(cls_id))
                if mapped_cls is None:
                    stats["boxes_skipped"] += 1
                    continue
                line_out = _to_yolo_line(mapped_cls, list(bbox), width, height)
            except Exception:
                line_out = None
            if line_out is None:
                stats["boxes_skipped"] += 1
                continue
            yolo_lines.append(line_out)

        lbl_dest.write_text("\n".join(yolo_lines) + ("\n" if yolo_lines else ""), encoding="utf-8")
        stats["labels_written"] += 1
        stats["boxes_written"] += len(yolo_lines)

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert HF imagefolder metadata to YOLO")
    parser.add_argument("--hf-root", type=Path, required=True, help="HF dataset root")
    parser.add_argument("--out-root", type=Path, required=True, help="Output YOLO root")
    parser.add_argument(
        "--splits",
        type=str,
        default="train,val",
        help="Comma-separated split names (default: train,val)",
    )
    parser.add_argument(
        "--copy-images",
        action="store_true",
        help="Copy images instead of symlinking (uses more disk)",
    )
    args = parser.parse_args()

    splits = [s.strip() for s in args.splits.split(",") if s.strip()]
    if not splits:
        print("[error] no splits provided")
        return 2

    total = {k: 0 for k in ("rows", "images_copied", "labels_written", "boxes_written", "rows_skipped", "boxes_skipped")}
    for split in splits:
        split_dir = args.hf_root / split
        out_split = "val" if split == "validation" else split
        out_dir = args.out_root / out_split
        if not split_dir.exists():
            print(f"[warn] split missing, skip: {split_dir}")
            continue
        stats = convert_split(split_dir, out_dir, link_images=not args.copy_images)
        for k, v in stats.items():
            total[k] += v
        print(
            f"{split}: rows={stats['rows']} images={stats['images_copied']} "
            f"labels={stats['labels_written']} boxes={stats['boxes_written']} "
            f"rows_skipped={stats['rows_skipped']} boxes_skipped={stats['boxes_skipped']}"
        )

    print(
        f"total: rows={total['rows']} images={total['images_copied']} "
        f"labels={total['labels_written']} boxes={total['boxes_written']} "
        f"rows_skipped={total['rows_skipped']} boxes_skipped={total['boxes_skipped']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
