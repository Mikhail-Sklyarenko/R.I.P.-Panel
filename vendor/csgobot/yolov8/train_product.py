#!/usr/bin/env python3
"""Train YOLO on the product dataset (TRAIN MACHINE ONLY — needs GPU + local dataset)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

YOLOV8 = Path(__file__).resolve().parent
DATASETS = YOLOV8 / "datasets"
DEFAULT_DATA = DATASETS / "product_data.yaml"
DEFAULT_BASE = YOLOV8 / "cs2_yolov8m_640_augmented_v4.pt"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fine-tune production weights on product_v1_bootstrap (or custom data yaml)."
    )
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--base-weights", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", type=str, default="0")
    parser.add_argument("--name", type=str, default="product_ctfix_v1")
    parser.add_argument("--patience", type=int, default=40)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)

    data = args.data.resolve()
    if not data.is_file():
        print(f"ERROR: data yaml missing: {data}")
        print("  On train PC first run BootstrapDataset.bat (builds product_v1_bootstrap).")
        return 1

    # Ultralytics resolves path: relative to yaml parent
    if data.name == "product_data_hn.yaml" or "product_v2_hn" in data.name:
        hn_root = DATASETS / "product_v2_hn" / "train" / "images"
        if not hn_root.is_dir() or not any(hn_root.iterdir()):
            print(f"ERROR: dataset images missing under {hn_root.parent}")
            print("  Run BuildProductWithHardNegatives.bat on this TRAIN machine.")
            return 1
    elif "product_v1" in data.name or data.name == "product_data.yaml":
        bootstrap = DATASETS / "product_v1_bootstrap" / "train" / "images"
        if not bootstrap.is_dir() or not any(bootstrap.iterdir()):
            print(f"ERROR: dataset images missing under {bootstrap.parent}")
            print("  Run BootstrapDataset.bat on this TRAIN machine only.")
            return 1

    base = args.base_weights.resolve()
    if not base.is_file():
        print(f"ERROR: base weights missing: {base}")
        print("  Run EnsureWeights.bat first (or place baseline .pt in yolov8/).")
        return 1

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        print(f"ERROR: ultralytics not installed in this Python: {exc}")
        print("  Use vendor/csgobot/venv")
        return 1

    print("=== TRAIN ONLY (not for farm PCs) ===")
    print(f"data: {data}")
    print(f"base: {base}")
    print(f"device: {args.device} epochs={args.epochs} batch={args.batch}")

    model = YOLO(str(base))
    model.train(
        data=str(data),
        imgsz=args.imgsz,
        epochs=args.epochs,
        batch=args.batch,
        device=args.device,
        patience=args.patience,
        workers=args.workers,
        name=args.name,
        resume=args.resume,
        project=str(YOLOV8 / "runs" / "detect"),
        exist_ok=True,
    )
    best = YOLOV8 / "runs" / "detect" / args.name / "weights" / "best.pt"
    print()
    print("OK: training finished")
    print(f"  best: {best}")
    print("Next (promote):")
    print(
        f'  python scripts/promote_weights.py "{best}" '
        f"--version v0.2.0-ctfix --filename cs2_yolov8m_640_product_v1.pt "
        f"--dataset-manifest vendor/csgobot/yolov8/datasets/manifests/product_v1_bootstrap_manifest.json"
    )
    print("  Host the .pt, set url + active in resources/csgobot/weights_registry.json")
    print("  Farm fleet: git pull && EnsureWeights.bat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
