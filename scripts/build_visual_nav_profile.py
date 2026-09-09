#!/usr/bin/env python3
"""Reproducibly build the bundled Dust2 visual MVP from repository assets.

Accepted HUD anchors are measured by multi-scale matching AND independent wall
contour agreement. The traversal mask is deliberately limited to the central
same-floor corridor shown by the supplied radar, not the entire map.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "csgobot"))

import cv2
import numpy as np

from nav.calibration import load_calibration
from nav.minimap_reader import MinimapReader
from nav.paths import resolve_calibration_path, resolve_map_radar_path
from nav.visual_localizer import VisualLocalizer


def build(destination):
    map_id = "de_dust2"
    radar_path = resolve_map_radar_path(map_id)
    radar = cv2.imread(str(radar_path))
    rgb_map = cv2.cvtColor(radar, cv2.COLOR_BGR2RGB)
    reader = MinimapReader(load_calibration(resolve_calibration_path()))
    # Explicit nonexistent profile avoids bootstrapping from a previous output.
    loc = VisualLocalizer(map_id, map_rgb=rgb_map, profile_dir=destination / "_no_existing_atlas")
    destination.mkdir(parents=True, exist_ok=True)
    references, rejected = [], []
    frames = sorted((ROOT / "resources/nav/maps/de_dust2/hud_ref").glob("*_frame.jpg"))
    for frame_path in frames:
        frame = cv2.cvtColor(cv2.imread(str(frame_path)), cv2.COLOR_BGR2RGB)
        reader.read(frame)
        if reader.last_circle is None:
            rejected.append(frame_path.name)
            continue
        crop, cx, cy, radius = reader._crop_from_circle(frame, reader.last_circle)
        yy, xx = np.ogrid[:crop.shape[0], :crop.shape[1]]
        d = (xx-cx)**2 + (yy-cy)**2
        mask = np.uint8((d < (radius-8)**2) & (d > 22**2))*255
        saturated = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)[:, :, 1] > 160
        mask[cv2.dilate(np.uint8(saturated), np.ones((7, 7), np.uint8)) > 0] = 0
        candidates = loc._map_candidates(crop, mask)
        if not candidates:
            rejected.append(frame_path.name)
            continue
        best = max(candidates, key=lambda r: r.confidence)
        crop[mask == 0] = 0
        name = frame_path.stem + ".png"
        if not cv2.imwrite(str(destination / name), cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)):
            raise OSError(f"Cannot save {name}")
        references.append({"image": name, "to_map": best.matrix.tolist(),
            "source_frame": frame_path.name, "source_sha256": hashlib.sha256(frame_path.read_bytes()).hexdigest(),
            "wall_agreement": round(best.confidence, 4), "inliers": best.inliers})
    if len(references) < 8:
        raise ValueError(f"Insufficient calibrated references: {len(references)}")
    (destination / "atlas.json").write_text(json.dumps({
        "map_id": map_id, "version": 1, "calibration_method": "multiscale_sift_plus_bidirectional_wall_contours",
        "references": references, "rejected_sources": rejected,
    }, indent=2) + "\n", encoding="utf-8")
    # Only the central lane, from lower mid to upper mid; no stairs, doors,
    # tunnels, drops, bridges or crossings to another level are inferred.
    b, g, r = (radar[:, :, i].astype(np.int16) for i in range(3))
    # The lane has a blue-ground shading gradient; gray boxes/walls must stay
    # excluded throughout that gradient rather than matching one flat color.
    floor = (b >= 75) & (b <= 95) & (b-r >= 15) & (g-r >= 10)
    region = np.zeros(radar.shape[:2], np.uint8)
    cv2.rectangle(region, (432, 403), (502, 636), 255, -1)
    mask = np.uint8(floor & (region > 0)) * 255
    if not cv2.imwrite(str(destination / "walkable.png"), mask):
        raise OSError("Cannot save walkable mask")
    (destination / "navigation.json").write_text(json.dumps({
        "map_id": map_id, "version": "1.0.0", "scope": "dust2_mid_lane",
        "clearance_px": 6, "resolution": [radar.shape[1], radar.shape[0]],
        "map_sha256": hashlib.sha256(radar_path.read_bytes()).hexdigest(),
        "route_pack": "dust2_visual_mvp", "live_validated": False,
        "mask_source": "radar floor palette intersected with inspected central lane rectangle; structures excluded",
        "supported_start_region": "central lane only; other spawns require manual positioning",
    }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"references": len(references), "rejected": rejected, "out": str(destination)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "resources/nav/profiles/de_dust2")
    build(parser.parse_args().out)
