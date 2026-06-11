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

    cuda_available = False
    device_name = ""
    torch_version = ""
    try:
        import torch
        from ultralytics import YOLO  # noqa: F401

        torch_version = str(getattr(torch, "__version__", ""))
        cuda_available = bool(torch.cuda.is_available())
        if cuda_available:
            try:
                device_name = str(torch.cuda.get_device_name(0))
            except Exception:
                device_name = "cuda:0"
        else:
            warnings.append("PyTorch on CPU — expect low FPS (install CUDA torch)")
    except Exception as exc:
        errors.append(f"torch/ultralytics import failed: {exc}")

    return {
        "ok": not errors,
        "warnings": warnings,
        "errors": errors,
        "cuda_available": cuda_available,
        "device_name": device_name,
        "torch_version": torch_version,
    }


def main() -> int:
    result = run_checks()
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
