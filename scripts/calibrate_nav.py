#!/usr/bin/env python3
"""
Offline minimap HUD calibration from farm PC screenshots.

Input: folder of 1280x720 DM frames (NOT committed — USB / local only).
Output: resources/nav/calibration_1280x720.yaml

Never writes to dataset_staging/ or YOLO train paths.
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import yaml
from PIL import Image


def _circle_edge_score(gray: np.ndarray, cx: int, cy: int, r: int, n: int = 72) -> float:
    angles = np.linspace(0, 2 * math.pi, n, endpoint=False)
    xs = (cx + r * np.cos(angles)).astype(int)
    ys = (cy + r * np.sin(angles)).astype(int)
    h, w = gray.shape
    ok = (xs >= 1) & (xs < w - 1) & (ys >= 1) & (ys < h - 1)
    xs, ys = xs[ok], ys[ok]
    if len(xs) < 10:
        return -1.0
    inner = gray[ys, xs - 1].astype(float)
    outer = gray[ys, xs + 1].astype(float)
    return float(np.mean(np.abs(outer - inner)))


def detect_minimap_circle(gray_top: np.ndarray) -> tuple[int, int, int]:
    best_score = -1.0
    best = (99, 100, 83)
    for cx in range(60, 190, 3):
        for cy in range(40, 190, 3):
            for r in range(65, 125, 3):
                score = _circle_edge_score(gray_top, cx, cy, r)
                if score > best_score:
                    best_score = score
                    best = (cx, cy, r)
    return best


def calibrate_player_rgb(crop: np.ndarray) -> tuple[list[int], list[int]]:
    r, g, b = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    mask = (g > 170) & (b > 170) & (r < 160)
    if mask.sum() < 5:
        return [0, 170, 170], [160, 255, 255]
    pts = np.column_stack([r[mask], g[mask], b[mask]])
    lo = np.percentile(pts, 5, axis=0).astype(int).tolist()
    hi = np.percentile(pts, 95, axis=0).astype(int).tolist()
    return lo, hi


def iter_frames(folder: Path) -> list[Path]:
    out: list[Path] = []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.name.startswith("._"):
            continue
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        if "копия" in path.name.lower() or " copy" in path.name.lower():
            continue
        if path.name.startswith("cap_") and "__soft_" in path.name:
            pass  # auto-capture ok for calibration only
        out.append(path)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path, help="Folder with 1280x720 frames")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "resources"
        / "nav"
        / "calibration_1280x720.yaml",
    )
    parser.add_argument("--max-frames", type=int, default=20)
    args = parser.parse_args()

    frames = iter_frames(args.input_dir)
    if not frames:
        print(f"no images in {args.input_dir}", file=sys.stderr)
        return 1

    circles: list[tuple[int, int, int]] = []
    rgb_mins: list[list[int]] = []
    rgb_maxs: list[list[int]] = []
    for path in frames[: args.max_frames]:
        img = np.asarray(Image.open(path).convert("RGB"))
        if img.shape[1] != 1280 or img.shape[0] != 720:
            print(f"skip {path.name}: expected 1280x720", file=sys.stderr)
            continue
        gray = np.asarray(Image.open(path).convert("L"))[:300, :300]
        cx, cy, r = detect_minimap_circle(gray)
        circles.append((cx, cy, r))
        x, y, w, h = cx - r, cy - r, 2 * r, 2 * r
        crop = img[y : y + h, x : x + w]
        lo, hi = calibrate_player_rgb(crop)
        rgb_mins.append(lo)
        rgb_maxs.append(hi)

    if not circles:
        print("no valid frames", file=sys.stderr)
        return 1

    cx = int(np.median([c[0] for c in circles]))
    cy = int(np.median([c[1] for c in circles]))
    r = int(np.median([c[2] for c in circles]))
    rect = {"x": cx - r, "y": cy - r, "w": 2 * r, "h": 2 * r}
    rgb_min = np.min(np.array(rgb_mins), axis=0).astype(int).tolist()
    rgb_max = np.max(np.array(rgb_maxs), axis=0).astype(int).tolist()

    data = {
        "meta": {
            "profile": "armoryfarm_1280x720",
            "resolution": [1280, 720],
            "calibrated_at": str(date.today()),
            "source": "offline_calibrate_nav",
            "frames_used": len(circles),
        },
        "minimap": {
            "rect": rect,
            "shape": "circle",
            "center": {"x": cx, "y": cy},
            "radius_px": r,
            "player_icon": {
                "mode": "color_blob",
                "rgb_min": rgb_min,
                "rgb_max": rgb_max,
                "min_area_px": 5,
                "max_area_px": 90,
                "prefer_center_px": 18,
            },
        },
        "pose": {
            "smooth_alpha": 0.35,
            "lost_timeout_sec": 0.8,
            "min_confidence": 0.35,
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
    print(f"wrote {args.out}")
    print(f"rect={rect} center=({cx},{cy}) r={r}")
    print(f"rgb_min={rgb_min} rgb_max={rgb_max}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
