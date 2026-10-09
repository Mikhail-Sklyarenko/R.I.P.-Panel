#!/usr/bin/env python3
"""Reproducible video registration report. Never sends game input."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor/csgobot'))

import cv2
from nav.calibration import load_calibration
from nav.minimap_reader import MinimapReader
from nav.paths import resolve_calibration_path
from nav.place_localizer import PlaceLocalizer
from nav.visual_perception import VisualPerception
from nav.release import identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map', dest='map_id', default='de_dust2')
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'data/nav_replay.json')
    parser.add_argument('--visual-profile', type=Path, help='Optional candidate atlas directory')
    parser.add_argument('--async-perception', action='store_true', help='Replay the product perception at real-time cadence')
    parser.add_argument('--start', type=float, default=0.)
    parser.add_argument('--seconds', type=float, default=60.)
    args = parser.parse_args()
    if args.visual_profile is not None and not (args.visual_profile / "atlas.json").is_file():
        parser.error("The selected visual profile has no atlas.json")
    if not 0 <= args.start or not 0 < args.seconds <= 3600:
        parser.error('Invalid start/duration')
    video = cv2.VideoCapture(str(args.video))
    if not video.isOpened():
        parser.error(f'Cannot open video: {args.video}')
    fps = video.get(cv2.CAP_PROP_FPS)
    if fps <= 0 or (video.get(cv2.CAP_PROP_FRAME_WIDTH), video.get(cv2.CAP_PROP_FRAME_HEIGHT)) != (1280, 720):
        video.release()
        parser.error('This profile requires a 1280x720 video with a valid FPS')
    run_identity = identity(args.map_id)
    if args.async_perception:
        from nav.async_perception import AsyncVisualPerception
        perception_type = AsyncVisualPerception
    else:
        perception_type = VisualPerception
    perception = perception_type(MinimapReader(load_calibration(resolve_calibration_path())), PlaceLocalizer(args.map_id), visual_profile=args.visual_profile)
    rows = []
    begin = int(args.start*fps)
    video.set(cv2.CAP_PROP_POS_FRAMES, begin)
    next_sample = args.start
    playback_started = time.monotonic()
    try:
        for index in range(begin, begin+int(args.seconds*fps)):
            ok, frame = video.read()
            if not ok:
                break
            stamp = index/fps
            if stamp+1e-6 < next_sample:
                continue
            next_sample += .1
            if args.async_perception:
                time.sleep(max(0., playback_started+stamp-args.start-time.monotonic()))
            observed = time.monotonic() if args.async_perception else 1+stamp
            started = time.perf_counter()
            result = perception.update(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), now=observed)
            p = result.pose
            reg = perception.visual.last_registration if not args.async_perception else None
            rows.append({'t': stamp, 'valid': p.valid, 'reason': perception.reason,
                         'x': p.x_norm, 'y': p.y_norm, 'yaw': p.yaw_deg,
                         'confidence': p.confidence, 'layer_id': p.layer_id, 'source': reg.source if reg else perception.reason,
                         'pose_age_ms': round((observed-p.observed_at)*1000,2) if p.valid else None,
                         'processing_ms': round((time.perf_counter()-started)*1000, 2)})
            if len(rows) % 100 == 0:
                print(f'Video {stamp:.1f}s: {len(rows)} samples processed', flush=True)
    finally:
        video.release()
        if args.async_perception:
            perception.close()
    if not rows:
        parser.error('No frames in the requested interval; no successful report was written')
    report = {**run_identity, 'video': args.video.name, 'sample_hz': 10, 'perception_mode': 'product_async' if args.async_perception else 'synchronous_reference', 'visual_profile': str(args.visual_profile) if args.visual_profile else None,
              'samples': len(rows), 'accepted': sum(row['valid'] for row in rows),
              'reasons': dict(Counter(row['reason'] for row in rows)),
              'note': 'Coverage is not accuracy. Includes menus/no-icon frames; no live movement is tested.', 'frames': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'frames'}, indent=2))
    print(f'Report: {args.output}')


if __name__ == '__main__':
    main()
