#!/usr/bin/env python3
"""Offline release check: no game, keyboard, mouse or model required."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor/csgobot"))

import cv2
from nav.calibration import load_calibration
from nav.minimap_reader import MinimapReader
from nav.pack import load_nav_pack
from nav.paths import resolve_calibration_path, resolve_nav_pack_path
from nav.place_localizer import PlaceLocalizer
from nav.release import identity
from nav.visual_perception import VisualPerception
from nav.walkable import WalkableMap


def check():
    pack = load_nav_pack(resolve_nav_pack_path("dust2_visual_mvp"))
    ground = WalkableMap.load(pack.map_id)
    points = [(g.x, g.y) for g in pack.goals]
    routes_ok = ground is not None and all(
        ground.plan(a, b) for a, b in zip(points, points[1:] + points[:1]))
    perception = VisualPerception(MinimapReader(load_calibration(resolve_calibration_path())),
                                  PlaceLocalizer(pack.map_id))
    rows = []
    for index, path in enumerate(sorted((ROOT / "resources/nav/maps/de_dust2/hud_ref").glob("*_frame.jpg"))):
        frame = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
        perception.reset()
        started = time.perf_counter()
        perception.update(frame, now=index + 1.)
        result = perception.update(frame, now=index + 1.1)
        rows.append({"frame": path.name, "accepted": bool(result.pose.valid),
                     "reason": perception.reason, "x": result.pose.x_norm,
                     "y": result.pose.y_norm, "confidence": result.pose.confidence,
                     "mean_update_ms": round((time.perf_counter() - started) * 500, 2)})
    accepted = sum(row["accepted"] for row in rows)
    return {**identity(pack.map_id), "pack": pack.pack_id,
            "offline_ready": bool(routes_ok and len(rows) == 22 and accepted == 22),
            "route_connected_both_directions": bool(routes_ok),
            "frames_accepted": accepted, "frames_total": len(rows),
            "live_validated": False,
            "scope": "Central Dust2 mid lane only; start inside the supplied mask",
            "evidence_limit": "19 atlas calibration images overlap this 22-frame corpus. Coverage is not independent accuracy or live traversal validation.",
            "frames": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/nav_acceptance.json")
    args = parser.parse_args()
    try:
        report = check()
    except Exception as exc:
        report = {"offline_ready": False, "live_validated": False, "error": str(exc)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "frames"}, indent=2))
    print(f"Report: {args.output}")
    return 0 if report["offline_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
