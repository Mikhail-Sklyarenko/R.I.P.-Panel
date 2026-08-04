"""Build product-ready YOLO dataset from one or more YOLO roots.

Input source format (per source root):
  <source>/<split>/images/*
  <source>/<split>/labels/*.txt

Output:
  <out-root>/<split>/images/*
  <out-root>/<split>/labels/*.txt

Features:
- deterministic split by scene key (prevents near-duplicate leakage);
- CT-priority reporting (for c/ch vs t/th);
- optional dedup by filename stem.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass(frozen=True)
class Sample:
    source_name: str
    scene_key: str
    stem: str
    image_path: Path
    label_path: Path

    @property
    def uid(self) -> str:
        return f"{self.source_name}__{self.stem}"


def _scene_key_from_stem(stem: str) -> str:
    # Convention: scene prefix before first "__" or first "_"
    if "__" in stem:
        return stem.split("__", 1)[0]
    if "_" in stem:
        return stem.split("_", 1)[0]
    return stem


def _list_split_pairs(split_dir: Path) -> list[tuple[Path, Path]]:
    images_dir = split_dir / "images"
    labels_dir = split_dir / "labels"
    if not images_dir.exists() or not labels_dir.exists():
        return []
    labels_by_stem = {p.stem: p for p in labels_dir.rglob("*.txt") if p.is_file()}
    out: list[tuple[Path, Path]] = []
    for ip in images_dir.rglob("*"):
        if not ip.is_file() or ip.suffix.lower() not in IMAGE_EXTS:
            continue
        lp = labels_by_stem.get(ip.stem)
        if lp is None:
            continue
        out.append((ip, lp))
    return out


def _collect_samples(source_root: Path, source_name: str) -> list[Sample]:
    out: list[Sample] = []
    for split in ("train", "val", "test"):
        split_dir = source_root / split
        for ip, lp in _list_split_pairs(split_dir):
            out.append(
                Sample(
                    source_name=source_name,
                    scene_key=_scene_key_from_stem(ip.stem),
                    stem=ip.stem,
                    image_path=ip,
                    label_path=lp,
                )
            )
    return out


def _assign_split(scene_key: str, train_pct: int, val_pct: int) -> str:
    h = int(hashlib.sha1(scene_key.encode("utf-8")).hexdigest(), 16) % 100
    if h < train_pct:
        return "train"
    if h < train_pct + val_pct:
        return "val"
    return "test"


def _assign_split_by_uid(uid: str, train_pct: int, val_pct: int) -> str:
    h = int(hashlib.sha1(uid.encode("utf-8")).hexdigest(), 16) % 100
    if h < train_pct:
        return "train"
    if h < train_pct + val_pct:
        return "val"
    return "test"


def _count_classes(label_path: Path, n_classes: int) -> Counter:
    c = Counter()
    for ln in label_path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        cls = int(float(ln.split()[0]))
        if 0 <= cls < n_classes:
            c[cls] += 1
    return c


def _mkdir_split(out_root: Path, split: str) -> tuple[Path, Path]:
    img = out_root / split / "images"
    lbl = out_root / split / "labels"
    img.mkdir(parents=True, exist_ok=True)
    lbl.mkdir(parents=True, exist_ok=True)
    return img, lbl


def build_dataset(
    sources: list[tuple[str, Path]],
    out_root: Path,
    class_names: list[str],
    train_pct: int,
    val_pct: int,
    dedup_stem: bool,
    link_images: bool,
) -> int:
    samples: list[Sample] = []
    for source_name, source_path in sources:
        src_samples = _collect_samples(source_path, source_name)
        samples.extend(src_samples)
        print(f"source={source_name} samples={len(src_samples)}")

    if not samples:
        print("[error] no input samples found")
        return 2

    if dedup_stem:
        uniq: dict[str, Sample] = {}
        for s in samples:
            uniq.setdefault(s.stem, s)
        samples = list(uniq.values())
        print(f"dedup by stem enabled -> samples={len(samples)}")

    unique_scenes = len({s.scene_key for s in samples})
    use_uid_split = unique_scenes < 20
    if use_uid_split:
        print(
            f"unique scene keys too low ({unique_scenes}), "
            "using uid-based deterministic split for healthier val/test."
        )

    stats_split_samples = Counter()
    stats_split_boxes: dict[str, Counter] = defaultdict(Counter)

    for sample in samples:
        if use_uid_split:
            split = _assign_split_by_uid(sample.uid, train_pct=train_pct, val_pct=val_pct)
        else:
            split = _assign_split(sample.scene_key, train_pct=train_pct, val_pct=val_pct)
        out_img_dir, out_lbl_dir = _mkdir_split(out_root, split)
        out_img = out_img_dir / f"{sample.uid}{sample.image_path.suffix.lower()}"
        out_lbl = out_lbl_dir / f"{sample.uid}.txt"
        if out_img.exists() or out_img.is_symlink():
            out_img.unlink()
        if link_images:
            out_img.symlink_to(sample.image_path.resolve())
        else:
            shutil.copy2(sample.image_path, out_img)
        shutil.copy2(sample.label_path, out_lbl)

        stats_split_samples[split] += 1
        stats_split_boxes[split].update(_count_classes(out_lbl, len(class_names)))

    print("\n# split stats")
    for split in ("train", "val", "test"):
        n = stats_split_samples[split]
        boxes_total = sum(stats_split_boxes[split].values())
        print(f"{split}: samples={n} boxes={boxes_total}")
        if boxes_total:
            for i, name in enumerate(class_names):
                c = stats_split_boxes[split][i]
                print(f"  - {i}:{name} -> {c} ({(c / boxes_total) * 100:.2f}%)")
            ct = stats_split_boxes[split][0] + stats_split_boxes[split][1]
            tt = stats_split_boxes[split][2] + stats_split_boxes[split][3]
            print(f"  - ct_share={(ct / boxes_total) * 100:.2f}% t_share={(tt / boxes_total) * 100:.2f}%")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build merged product-ready YOLO dataset")
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        help="Source in form name=/abs/or/relative/path",
    )
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--classes", type=str, default="c,ch,t,th")
    parser.add_argument("--train-pct", type=int, default=80)
    parser.add_argument("--val-pct", type=int, default=10)
    parser.add_argument("--dedup-stem", action="store_true")
    parser.add_argument(
        "--copy-images",
        action="store_true",
        help="Copy images instead of symlinking (uses more disk)",
    )
    args = parser.parse_args()

    if args.train_pct <= 0 or args.val_pct < 0 or args.train_pct + args.val_pct >= 100:
        print("[error] invalid split percentages")
        return 2

    class_names = [x.strip() for x in args.classes.split(",") if x.strip()]
    if len(class_names) < 4:
        print("[error] expected at least 4 class names, e.g. c,ch,t,th")
        return 2

    sources: list[tuple[str, Path]] = []
    for raw in args.source:
        if "=" not in raw:
            print(f"[error] invalid --source format: {raw}")
            return 2
        name, p = raw.split("=", 1)
        source_path = Path(p).expanduser().resolve()
        if not source_path.exists():
            print(f"[error] source path does not exist: {source_path}")
            return 2
        sources.append((name.strip(), source_path))

    return build_dataset(
        sources=sources,
        out_root=args.out_root.resolve(),
        class_names=class_names,
        train_pct=args.train_pct,
        val_pct=args.val_pct,
        dedup_stem=args.dedup_stem,
        link_images=not args.copy_images,
    )


if __name__ == "__main__":
    raise SystemExit(main())
