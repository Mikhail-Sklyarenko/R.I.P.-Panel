#!/usr/bin/env python3
"""Sort existing dataset archives into train-safe export + quarantine.

Reads extracted staging (captures, our_cs2_BAD, hard_negatives) and full
product_v1_bootstrap. Writes dataset_export/ for copy to Train PC.

Does NOT delete originals. Quarantine = never merge to train.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SPLITS = ("train", "val", "test")
CLASS_NAMES = ("c", "ch", "t", "th")


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_stem(prefix: str, stem: str, max_len: int = 160) -> str:
    raw = f"{prefix}_{stem}"[:max_len]
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in raw)


def parse_yolo_boxes(text: str) -> list[tuple[int, float, float, float, float]]:
    out: list[tuple[int, float, float, float, float]] = []
    for ln in text.splitlines():
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
        out.append((cls, *vals))  # type: ignore[misc]
    return out


def is_suspicious_box(w: float, h: float, area_thresh: float, min_dim: float) -> bool:
    if w * h < area_thresh:
        return True
    if min(w, h) < min_dim:
        return True
    return False


def copy_pair(
    img: Path,
    lbl: Path | None,
    out_img_dir: Path,
    out_lbl_dir: Path,
    stem: str,
    empty_label: bool,
    seen_hash: set[str],
) -> bool:
    digest = sha1_file(img)
    if digest in seen_hash:
        return False
    seen_hash.add(digest)
    out_img_dir.mkdir(parents=True, exist_ok=True)
    out_lbl_dir.mkdir(parents=True, exist_ok=True)
    dst_img = out_img_dir / f"{stem}{img.suffix.lower()}"
    dst_lbl = out_lbl_dir / f"{stem}.txt"
    shutil.copy2(img, dst_img)
    if empty_label:
        dst_lbl.write_text("", encoding="utf-8")
    elif lbl and lbl.is_file():
        shutil.copy2(lbl, dst_lbl)
    else:
        dst_lbl.write_text("", encoding="utf-8")
    return True


def merge_yolo_tree(
    src_root: Path,
    out_root: Path,
    prefix: str,
    split_map: dict[str, str] | None,
    empty_only: bool,
    seen_hash: set[str],
    stats: Counter,
) -> None:
    """Copy images+labels from YOLO split tree into out_root."""
    if not src_root.is_dir():
        return
    for split in SPLITS:
        split_dir = src_root / split
        images_dir = split_dir / "images"
        labels_dir = split_dir / "labels"
        if not images_dir.is_dir():
            continue
        out_split = split_map.get(split, split) if split_map else split
        out_img = out_root / out_split / "images"
        out_lbl = out_root / out_split / "labels"
        for img in sorted(images_dir.rglob("*")):
            if not img.is_file() or img.suffix.lower() not in IMAGE_EXTS:
                continue
            lbl = labels_dir / f"{img.stem}.txt"
            text = lbl.read_text(encoding="utf-8").strip() if lbl.is_file() else ""
            boxes = parse_yolo_boxes(text)
            if empty_only and boxes:
                continue
            stem = safe_stem(prefix, img.stem)
            if copy_pair(img, lbl if lbl.is_file() else None, out_img, out_lbl, stem, not boxes, seen_hash):
                stats["hn_added"] += 1
                stats[f"hn_{out_split}"] += 1


def process_captures(
    captures_root: Path,
    hn_root: Path,
    quarantine_root: Path,
    seen_hash: set[str],
    stats: Counter,
    manifest_only: bool,
) -> None:
    if not captures_root.is_dir():
        return
    q_manifest: list[dict] = []
    hn_img = hn_root / "train" / "images"
    hn_lbl = hn_root / "train" / "labels"
    for img in captures_root.rglob("*"):
        if not img.is_file() or img.suffix.lower() not in IMAGE_EXTS:
            continue
        if img.parent.name != "images":
            continue
        session = img.parent.parent
        lbl = session / "labels_soft" / f"{img.stem}.txt"
        text = lbl.read_text(encoding="utf-8").strip() if lbl.is_file() else ""
        boxes = parse_yolo_boxes(text)
        if boxes:
            stats["quarantine_captures_soft"] += 1
            if manifest_only:
                q_manifest.append(
                    {
                        "image": str(img),
                        "label": str(lbl) if lbl.is_file() else "",
                        "reason": "soft_positive_poison",
                    }
                )
            else:
                q_img = quarantine_root / "captures_soft_positive" / "images"
                q_lbl = quarantine_root / "captures_soft_positive" / "labels"
                stem = safe_stem("cap_poison", img.stem)
                copy_pair(img, lbl if lbl.is_file() else None, q_img, q_lbl, stem, False, set())
        else:
            stem = safe_stem("cap_empty", img.stem)
            if copy_pair(img, None, hn_img, hn_lbl, stem, True, seen_hash):
                stats["hn_from_captures_empty"] += 1
    if manifest_only and q_manifest:
        quarantine_root.mkdir(parents=True, exist_ok=True)
        path = quarantine_root / "captures_soft_positive_manifest.json"
        path.write_text(json.dumps(q_manifest, indent=2), encoding="utf-8")


def quarantine_bad(bad_root: Path, quarantine_root: Path, stats: Counter, manifest_only: bool) -> None:
    if not bad_root.is_dir():
        return
    if manifest_only:
        entries = []
        for img in bad_root.rglob("*"):
            if not img.is_file() or img.suffix.lower() not in IMAGE_EXTS:
                continue
            lbl = img.parent.parent / "labels" / f"{img.stem}.txt"
            if not lbl.is_file():
                lbl = img.parent.parent.parent / "labels" / f"{img.stem}.txt"
            # labels sit in split/labels
            for split in SPLITS:
                alt = bad_root / split / "labels" / f"{img.stem}.txt"
                if alt.is_file():
                    lbl = alt
                    break
            entries.append(
                {
                    "image": str(img),
                    "label": str(lbl) if lbl.is_file() else "",
                    "reason": "our_cs2_BAD_poison",
                }
            )
        quarantine_root.mkdir(parents=True, exist_ok=True)
        (quarantine_root / "our_cs2_BAD_manifest.json").write_text(
            json.dumps(entries, indent=2), encoding="utf-8"
        )
        stats["quarantine_bad_images"] = len(entries)
        return
    dst = quarantine_root / "our_cs2_BAD_DO_NOT_USE"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(bad_root, dst)
    n = sum(1 for p in dst.rglob("*") if p.suffix.lower() in IMAGE_EXTS)
    stats["quarantine_bad_images"] = n


def audit_bootstrap_train(
    bootstrap_root: Path,
    quarantine_root: Path,
    exclude_stems: list[str],
    stats: Counter,
    area_thresh: float,
    min_dim: float,
    manifest_only: bool,
) -> None:
    train_img = bootstrap_root / "train" / "images"
    train_lbl = bootstrap_root / "train" / "labels"
    if not train_img.is_dir():
        return
    q_manifest: list[dict] = []
    q_img = quarantine_root / "bootstrap_train_suspicious" / "images"
    q_lbl = quarantine_root / "bootstrap_train_suspicious" / "labels"
    seen_q: set[str] = set()
    for img in sorted(train_img.rglob("*")):
        if not img.is_file() or img.suffix.lower() not in IMAGE_EXTS:
            continue
        lbl = train_lbl / f"{img.stem}.txt"
        if not lbl.is_file():
            continue
        text = lbl.read_text(encoding="utf-8").strip()
        boxes = parse_yolo_boxes(text)
        if not boxes:
            continue
        suspicious = any(is_suspicious_box(w, h, area_thresh, min_dim) for _, _, _, w, h in boxes)
        if not suspicious:
            continue
        exclude_stems.append(img.stem)
        stats["quarantine_bootstrap_suspicious"] += 1
        if manifest_only:
            q_manifest.append(
                {
                    "image": str(img),
                    "label": str(lbl),
                    "reason": "suspicious_tiny_box",
                }
            )
        else:
            stem = safe_stem("boot_susp", img.stem)
            copy_pair(img, lbl, q_img, q_lbl, stem, False, seen_q)
    if manifest_only and q_manifest:
        quarantine_root.mkdir(parents=True, exist_ok=True)
        (quarantine_root / "bootstrap_train_suspicious_manifest.json").write_text(
            json.dumps(q_manifest, indent=2), encoding="utf-8"
        )


def build_filtered_bootstrap(
    bootstrap_root: Path,
    out_root: Path,
    exclude_train_stems: set[str],
    stats: Counter,
) -> None:
    """Copy bootstrap; skip suspicious train stems (train only)."""
    for split in SPLITS:
        src_split = bootstrap_root / split
        if not src_split.is_dir():
            continue
        dst_split = out_root / split
        for sub in ("images", "labels"):
            (dst_split / sub).mkdir(parents=True, exist_ok=True)
        images_dir = src_split / "images"
        labels_dir = src_split / "labels"
        if not images_dir.is_dir():
            continue
        for img in sorted(images_dir.rglob("*")):
            if not img.is_file() or img.suffix.lower() not in IMAGE_EXTS:
                continue
            if split == "train" and img.stem in exclude_train_stems:
                stats["bootstrap_train_excluded"] += 1
                continue
            lbl = labels_dir / f"{img.stem}.txt"
            shutil.copy2(img, dst_split / "images" / img.name)
            if lbl.is_file():
                shutil.copy2(lbl, dst_split / "labels" / lbl.name)
            else:
                (dst_split / "labels" / f"{img.stem}.txt").write_text("", encoding="utf-8")
            stats[f"bootstrap_{split}_kept"] += 1


def import_bootstrap_empties(
    bootstrap_root: Path,
    hn_root: Path,
    seen_hash: set[str],
    stats: Counter,
) -> None:
    for split in SPLITS:
        images_dir = bootstrap_root / split / "images"
        labels_dir = bootstrap_root / split / "labels"
        if not images_dir.is_dir():
            continue
        out_split = split
        out_img = hn_root / out_split / "images"
        out_lbl = hn_root / out_split / "labels"
        for img in sorted(images_dir.rglob("*")):
            if not img.is_file() or img.suffix.lower() not in IMAGE_EXTS:
                continue
            lbl = labels_dir / f"{img.stem}.txt"
            text = lbl.read_text(encoding="utf-8").strip() if lbl.is_file() else ""
            if text:
                continue
            stem = safe_stem("boot_empty", img.stem)
            if copy_pair(img, None, out_img, out_lbl, stem, True, seen_hash):
                stats["hn_from_bootstrap_empty"] += 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Sort datasets → export + quarantine")
    parser.add_argument(
        "--staging",
        type=Path,
        default=Path("dataset_staging"),
        help="Extracted captures, BAD, hard_negatives",
    )
    parser.add_argument(
        "--bootstrap",
        type=Path,
        default=Path("vendor/csgobot/yolov8/datasets/product_v1_bootstrap"),
    )
    parser.add_argument(
        "--export",
        type=Path,
        default=Path("dataset_export"),
    )
    parser.add_argument("--area-thresh", type=float, default=0.004, help="Suspicious box area w*h")
    parser.add_argument("--manifest-only-quarantine", action="store_true", default=True)
    parser.add_argument("--no-manifest-only-quarantine", action="store_false", dest="manifest_only_quarantine")
    parser.add_argument("--min-dim", type=float, default=0.02, help="Suspicious min side")
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Merge HN into vendor/csgobot datasets (no duplicate export tree)",
    )
    args = parser.parse_args()

    repo = Path.cwd()
    staging = args.staging if args.staging.is_absolute() else repo / args.staging
    bootstrap = args.bootstrap if args.bootstrap.is_absolute() else repo / args.bootstrap
    export = args.export if args.export.is_absolute() else repo / args.export

    export.mkdir(parents=True, exist_ok=True)
    quarantine = export / "quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)

    ws_root = repo / "vendor/csgobot/yolov8/datasets"
    if args.in_place:
        hn_out = ws_root / "sources/hard_negatives"
        bootstrap_out = ws_root / "product_v1_bootstrap_clean"
        our_cs2_empty = ws_root / "sources/our_cs2"
    else:
        hn_out = export / "vendor/csgobot/yolov8/datasets/sources/hard_negatives"
        bootstrap_out = export / "vendor/csgobot/yolov8/datasets/product_v1_bootstrap"
        our_cs2_empty = export / "vendor/csgobot/yolov8/datasets/sources/our_cs2"

    for split in SPLITS:
        (our_cs2_empty / split / "images").mkdir(parents=True, exist_ok=True)
        (our_cs2_empty / split / "labels").mkdir(parents=True, exist_ok=True)
        for sub in our_cs2_empty.glob(f"{split}/images/*"):
            if sub.is_file() and sub.name != ".gitkeep":
                sub.unlink()
        for sub in our_cs2_empty.glob(f"{split}/labels/*.txt"):
            if sub.is_file() and sub.name != ".gitkeep":
                sub.unlink()
        gitkeep = our_cs2_empty / split / "images" / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")

    stats: Counter = Counter()
    seen_hash: set[str] = set()

    # Dedup against existing HN content
    if hn_out.is_dir():
        for img in hn_out.rglob("*"):
            if img.is_file() and img.suffix.lower() in IMAGE_EXTS:
                seen_hash.add(sha1_file(img))

    hn_staging = staging / "hard_negatives"
    if hn_staging.is_dir():
        merge_yolo_tree(hn_staging, hn_out, "hn_arc", None, empty_only=True, seen_hash=seen_hash, stats=stats)

    ws_hn = ws_root / "sources/hard_negatives"
    if not args.in_place and ws_hn.is_dir() and ws_hn.resolve() != hn_out.resolve():
        merge_yolo_tree(ws_hn, hn_out, "hn_ws", None, empty_only=True, seen_hash=seen_hash, stats=stats)

    bad_root = staging / "our_cs2_BAD_DO_NOT_USE"
    quarantine_bad(bad_root, quarantine, stats, args.manifest_only_quarantine)

    captures_root = staging / "captures"
    if not captures_root.is_dir():
        alt = staging / "data" / "captures"
        captures_root = alt if alt.is_dir() else captures_root
    process_captures(
        captures_root,
        hn_out,
        quarantine,
        seen_hash,
        stats,
        args.manifest_only_quarantine,
    )

    exclude_stems: list[str] = []
    bootstrap_images = sum(
        1 for p in bootstrap.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    bootstrap_labels = sum(1 for p in bootstrap.rglob("labels/*.txt") if p.is_file())
    stats["bootstrap_images_on_disk"] = bootstrap_images
    stats["bootstrap_labels_on_disk"] = bootstrap_labels

    report_note = ""
    if bootstrap.is_dir() and bootstrap_images >= 5000:
        audit_bootstrap_train(
            bootstrap,
            quarantine,
            exclude_stems,
            stats,
            args.area_thresh,
            args.min_dim,
            args.manifest_only_quarantine,
        )
        exclude_set = set(exclude_stems)
        build_filtered_bootstrap(bootstrap, bootstrap_out, exclude_set, stats)
        import_bootstrap_empties(bootstrap, hn_out, seen_hash, stats)
    elif bootstrap.is_dir():
        stats["bootstrap_skipped_filtered"] = 1
        report_note = (
            f"INCOMPLETE bootstrap: {bootstrap_images} images vs {bootstrap_labels} labels. "
            "Re-extract product_v1_bootstrap.rar before train."
        )
    else:
        report_note = "bootstrap path missing."

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": dict(stats),
        "exclude_train_stems_count": len(exclude_stems),
        "hn_total_images": sum(
            1 for p in hn_out.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        ),
        "bootstrap_train_images": sum(
            1 for p in (bootstrap_out / "train" / "images").rglob("*")
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        )
        if (bootstrap_out / "train").is_dir()
        else 0,
        "bootstrap_complete": bootstrap_images >= 5000,
        "note": report_note if bootstrap.is_dir() and bootstrap_images < 5000 else "",
        "paths": {
            "export_root": str(export),
            "bootstrap_out": str(bootstrap_out),
            "hard_negatives": str(hn_out),
            "quarantine": str(quarantine),
            "our_cs2_scaffold": str(our_cs2_empty),
        },
        "train_rules": [
            "Train with product_v1_bootstrap_clean if complete, else full bootstrap from USB rar.",
            "Use sources/hard_negatives (merged, deduped).",
            "sources/our_cs2 must stay empty — never merge BAD.",
            "quarantine manifests are NOT for training.",
        ],
    }
    (export / "SORT_REPORT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Dataset sort report",
        f"Generated: {report['generated_at']}",
        "",
        "## Counts",
    ]
    for k, v in sorted(stats.items()):
        lines.append(f"- {k}: {v}")
    lines.extend(
        [
            f"- hn_total_images: {report['hn_total_images']}",
            f"- bootstrap_train_images: {report['bootstrap_train_images']}",
            f"- exclude_train_stems: {report['exclude_train_stems_count']}",
            f"- bootstrap_complete: {report['bootstrap_complete']}",
        ]
    )
    if report.get("note"):
        lines.append(f"- note: {report['note']}")

    if exclude_stems:
        (export / "exclude_train_stems.txt").write_text("\n".join(exclude_stems) + "\n", encoding="utf-8")

    copy_cmd = (
        "hard_negatives updated in vendor/csgobot (in-place)."
        if args.in_place
        else "Copy dataset_export/vendor → R.I.P.-Panel/vendor"
    )
    lines.extend(
        [
            "",
            "## Train PC",
            copy_cmd,
            "If bootstrap_complete is false: extract product_v1_bootstrap.rar on Train PC.",
            "BuildProductWithHardNegatives.bat",
            "TrainProductModel.bat --data vendor\\csgobot\\yolov8\\datasets\\product_data_hn.yaml --name product_golden_v1",
        ]
    )
    (export / "SORT_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
