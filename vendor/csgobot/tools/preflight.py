"""Quick csgobot dependency check for panel preflight. Prints JSON to stdout."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEIGHTS = ROOT / "yolov8" / "cs2_yolov8m_640_augmented_v4.pt"


def run_checks() -> dict[str, object]:
    warnings: list[str] = []
    errors: list[str] = []
    nav: dict[str, object] | None = None

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

    nav_enabled = os.environ.get("CSGOBOT_NAV", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if nav_enabled:
        try:
            from nav.preflight import run_nav_preflight

            pack_id = os.environ.get("CSGOBOT_NAV_PACK", "auto").strip() or "auto"
            cal_path = os.environ.get("CSGOBOT_NAV_CALIBRATION", "").strip()
            nav = run_nav_preflight(pack_id=pack_id, calibration_path=cal_path)
            for msg in nav.get("warnings", []):
                warnings.append(f"nav: {msg}")
            for msg in nav.get("errors", []):
                errors.append(f"nav: {msg}")
        except Exception as exc:
            errors.append(f"nav preflight failed: {exc}")

    result: dict[str, object] = {
        "ok": not errors,
        "warnings": warnings,
        "errors": errors,
        "cuda_available": cuda_available,
        "device_name": device_name,
        "torch_version": torch_version,
    }
    if nav is not None:
        result["nav"] = nav
    result["ok"] = not errors
    return result


def main() -> int:
    result = run_checks()
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
