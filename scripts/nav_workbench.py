#!/usr/bin/env python3
"""Author navigation profiles and replay video without sending keyboard input.

Use the csgobot Python environment (OpenCV with GUI for mask/atlas commands).
All profile paths are under FARM_PANEL_DATA_DIR/nav_profiles/<map_id>.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "csgobot"))

import cv2
import numpy as np

from nav.calibration import load_calibration
from nav.minimap_reader import MinimapReader
from nav.paths import resolve_calibration_path, resolve_map_radar_path, resolve_visual_profile_dir
from nav.place_localizer import PlaceLocalizer
from nav.visual_perception import VisualPerception


def read_map(map_id):
    image = cv2.imread(str(resolve_map_radar_path(map_id)))
    if image is None:
        raise ValueError("Map radar image not found")
    return image


def write_json(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def edit_mask(args):
    if not math.isfinite(args.clearance) or args.clearance < 1:
        raise ValueError("clearance must be finite and >= 1 map pixel")
    source = read_map(args.map_id)
    folder = resolve_visual_profile_dir(args.map_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "walkable.png"
    mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if path.exists() else None
    if mask is None:
        mask = np.zeros(source.shape[:2], np.uint8)
    if mask.shape != source.shape[:2]:
        raise ValueError("Existing mask resolution differs from radar")
    scale = min(1., 850 / max(source.shape[:2]))
    points, undo = [], []
    title = "Walkable: click polygon; ENTER add; X block; U undo; S save; ESC cancel"
    cv2.namedWindow(title)

    def click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append((round(x / scale), round(y / scale)))
        elif event == cv2.EVENT_RBUTTONDOWN and points:
            points.pop()
    cv2.setMouseCallback(title, click)
    try:
        while True:
            preview = source.copy()
            preview[mask >= 250] = (preview[mask >= 250] * .45 + np.array([40, 200, 50]) * .55).astype(np.uint8)
            if len(points) > 1:
                cv2.polylines(preview, [np.int32(points)], False, (0, 255, 255), 2)
            for point in points:
                cv2.circle(preview, point, 3, (0, 255, 255), -1)
            cv2.imshow(title, cv2.resize(preview, None, fx=scale, fy=scale))
            key = cv2.waitKey(30) & 255
            if key == 27:
                return
            if key in (13, 10, ord("x")) and len(points) >= 3:
                undo.append(mask.copy())
                cv2.fillPoly(mask, [np.int32(points)], 0 if key == ord("x") else 255)
                points.clear()
            elif key == ord("u") and undo:
                mask = undo.pop()
                points.clear()
            elif key == ord("s"):
                if points:
                    print("Finish the polygon with ENTER or remove points before saving.")
                    continue
                if not np.any(mask):
                    raise ValueError("Empty mask: no walkable ground annotated")
                if not cv2.imwrite(str(path), mask):
                    raise OSError("Could not save walkable mask")
                write_json(folder / "navigation.json", {
                    "map_id": args.map_id, "clearance_px": args.clearance,
                    "resolution": [source.shape[1], source.shape[0]],
                    "limitations": "Single floor. Stairs/doors must be verified in-game; no jumps or drops inferred.",
                })
                print(path)
                return
    finally:
        cv2.destroyAllWindows()


def fit_anchors(source, target):
    src, dst = np.float32(source), np.float32(target)
    if src.shape != dst.shape or len(src) < 4 or src.ndim != 2 or src.shape[1] != 2 or not np.isfinite(src).all() or not np.isfinite(dst).all():
        raise ValueError("At least four finite paired points are required")
    if cv2.contourArea(cv2.convexHull(src)) < 300:
        raise ValueError("Spread anchors across the radar, not along one edge")
    matrix, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.LMEDS)
    if matrix is None:
        raise ValueError("Could not fit anchors")
    errors = np.linalg.norm(src @ matrix[:, :2].T + matrix[:, 2] - dst, axis=1)
    if float(errors.max()) > 8:
        raise ValueError(f"Anchors disagree: maximum map error {errors.max():.1f}px (limit 8)")
    return matrix


def add_atlas(args):
    source = read_map(args.map_id)
    frame = cv2.imread(str(args.frame))
    if frame is None:
        raise ValueError("Cannot read frame")
    reader = MinimapReader(load_calibration(resolve_calibration_path(args.calibration)))
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    reader.read(rgb)
    if reader.last_circle is None:
        raise ValueError("Radar circle not found")
    crop, cx, cy, radius = reader._crop_from_circle(rgb, reader.last_circle)
    crop = cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)
    yy, xx = np.ogrid[:crop.shape[0], :crop.shape[1]]
    keep = ((xx-cx)**2 + (yy-cy)**2 < (radius - 7)**2) & ((xx-cx)**2 + (yy-cy)**2 > 22**2)
    crop[~keep] = 0
    if args.anchors:
        pairs = json.loads(args.anchors.read_text(encoding="utf-8"))
        src, dst = pairs["radar_pixels"], pairs["map_pixels"]
    else:
        radar_scale, map_scale = 2., min(1., 760/max(source.shape[:2]))
        left = cv2.resize(crop, None, fx=radar_scale, fy=radar_scale)
        right = cv2.resize(source, None, fx=map_scale, fy=map_scale)
        canvas = np.zeros((max(left.shape[0], right.shape[0]), left.shape[1]+right.shape[1], 3), np.uint8)
        canvas[:left.shape[0], :left.shape[1]] = left
        canvas[:right.shape[0], left.shape[1]:] = right
        src, dst = [], []
        title = "Pair same wall corners: RADAR then MAP; >=4 pairs; S save; U undo; ESC cancel"
        cv2.namedWindow(title)
        def click(event, x, y, flags, param):
            if event != cv2.EVENT_LBUTTONDOWN:
                return
            if len(src) == len(dst) and x < left.shape[1] and y < left.shape[0]:
                src.append((x/radar_scale, y/radar_scale))
            elif len(src) > len(dst) and x >= left.shape[1] and y < right.shape[0]:
                dst.append(((x-left.shape[1])/map_scale, y/map_scale))
        cv2.setMouseCallback(title, click)
        try:
            while True:
                preview = canvas.copy()
                for i, (x, y) in enumerate(src):
                    cv2.putText(preview, str(i+1), (int(x*radar_scale), int(y*radar_scale)), 0, .6, (0, 255, 255), 2)
                for i, (x, y) in enumerate(dst):
                    cv2.putText(preview, str(i+1), (int(x*map_scale)+left.shape[1], int(y*map_scale)), 0, .6, (0, 255, 255), 2)
                cv2.imshow(title, preview)
                key = cv2.waitKey(30) & 255
                if key == 27:
                    return
                if key == ord("u"):
                    if len(src) > len(dst):
                        src.pop()
                    elif src:
                        src.pop(); dst.pop()
                if key == ord("s"):
                    try:
                        fit_anchors(src, dst)
                        break
                    except ValueError as exc:
                        print(exc)
        finally:
            cv2.destroyAllWindows()
    matrix = fit_anchors(src, dst)
    folder = resolve_visual_profile_dir(args.map_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "atlas.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"map_id": args.map_id, "references": []}
    name = f"reference_{len(data['references'])+1:03d}.png"
    if not cv2.imwrite(str(folder / name), crop):
        raise OSError("Could not save radar crop")
    data["references"].append({"image": name, "to_map": matrix.tolist(), "radar_pixels": src, "map_pixels": dst})
    write_json(path, data)
    print(path)


def replay(args):
    reader = MinimapReader(load_calibration(resolve_calibration_path(args.calibration)))
    perception = VisualPerception(reader, PlaceLocalizer(args.map_id))
    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise ValueError("Could not open video")
    fps = capture.get(cv2.CAP_PROP_FPS)
    if not np.isfinite(fps) or fps <= 0:
        raise ValueError("Video FPS missing")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    valid = total = 0
    writer = None
    try:
        with args.output.open("w", encoding="utf-8") as log:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                now = 1. + total / fps
                result = perception.update(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), now=now)
                p = result.pose
                total += 1
                valid += int(p.valid)
                record = {"time": now, "valid": p.valid, "x": p.x_norm, "y": p.y_norm,
                          "yaw": p.yaw_deg, "confidence": p.confidence,
                          "observed_at": p.observed_at, "reason": perception.reason}
                log.write(json.dumps(record) + "\n")
                if args.overlay:
                    if writer is None:
                        writer = cv2.VideoWriter(str(args.overlay), cv2.VideoWriter_fourcc(*"mp4v"), fps, (frame.shape[1], frame.shape[0]))
                        if not writer.isOpened():
                            raise ValueError("Could not create overlay video")
                    text = f"{perception.reason} xy=({p.x_norm:.3f},{p.y_norm:.3f}) yaw={p.yaw_deg:.0f} conf={p.confidence:.2f}"
                    cv2.putText(frame, text, (15, frame.shape[0]-20), 0, .55, (0,255,0) if p.valid else (0,0,255), 2)
                    writer.write(frame)
    finally:
        capture.release()
        if writer:
            writer.release()
    print(json.dumps({"frames": total, "valid_frames": valid, "coverage": valid/max(1,total),
                      "note": "Coverage is not accuracy; compare against independent ground truth."}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("mask", "atlas", "replay"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--map-id", default="de_dust2")
        cmd.add_argument("--calibration", default="")
        if name == "mask":
            cmd.add_argument("--clearance", type=float, default=8.)
            cmd.set_defaults(func=edit_mask)
        elif name == "atlas":
            cmd.add_argument("--frame", type=Path, required=True)
            cmd.add_argument("--anchors", type=Path)
            cmd.set_defaults(func=add_atlas)
        else:
            cmd.add_argument("--video", type=Path, required=True)
            cmd.add_argument("--output", type=Path, required=True)
            cmd.add_argument("--overlay", type=Path)
            cmd.set_defaults(func=replay)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
