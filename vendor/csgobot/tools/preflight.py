"""Quick csgobot dependency check for panel preflight. Prints JSON to stdout."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEIGHTS = ROOT / "yolov8" / "cs2_yolov8m_640_augmented_v4.pt"


def run_checks() -> dict[str, object]:
    warnings: list[str] = []
    errors: list[str] = []

    if not WEIGHTS.is_file():
        errors.append(f"weights missing: {WEIGHTS.name}")

    try:
        from pygrabber.dshow_graph import FilterGraph  # noqa: F401
    except Exception as exc:
        errors.append(f"pygrabber import failed: {exc}")

    try:
        import torch
        from ultralytics import YOLO  # noqa: F401

        if not torch.cuda.is_available():
            warnings.append("PyTorch on CPU — expect low FPS (install CUDA torch)")
    except Exception as exc:
        errors.append(f"torch/ultralytics import failed: {exc}")

    return {"ok": not errors, "warnings": warnings, "errors": errors}


def main() -> int:
    result = run_checks()
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
