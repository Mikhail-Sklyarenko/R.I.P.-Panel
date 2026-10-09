#!/usr/bin/env python3
"""Rebuild Inferno's versioned mask and calibrated HUD atlas from its recording."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor/csgobot'))
import cv2
import numpy as np
from nav.calibration import load_calibration
from nav.minimap_reader import MinimapReader
from nav.paths import resolve_calibration_path


def build_mask(radar, regions):
    h, s, v = cv2.split(cv2.cvtColor(radar, cv2.COLOR_BGR2HSV))
    floor = (v >= 40) & (v <= 90)
    floor |= ((h >= 5) & (h <= 32) & (s >= 90) & (v >= 65) & (v <= 195))
    floor |= ((h >= 35) & (h <= 85) & (s >= 60) & (v >= 65) & (v <= 195))
    mask = np.uint8(floor) * 255
    for region in regions['blocked_transitions']:
        cv2.fillPoly(mask, [np.array(region['points'], np.int32)], 0)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
    for i in range(1, count):
        if stats[i, 4] < 150:
            mask[labels == i] = 0
    return mask


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Output must be a new directory')
    source = ROOT / 'resources/nav/profiles/de_inferno'
    maps = ROOT / 'resources/nav/maps/de_inferno'
    atlas = json.loads((source / 'atlas.json').read_text())
    regions = json.loads((maps / 'floor_regions.json').read_text())
    if hashlib.sha256(args.video.read_bytes()).hexdigest() != atlas['source_sha256']:
        parser.error('Video differs from the calibrated recording')
    if hashlib.sha256((maps / 'radar.png').read_bytes()).hexdigest() != regions['map_sha256']:
        parser.error('Radar changed: floor and atlas coordinates need review')
    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened() or (cap.get(3), cap.get(4)) != (1280, 720):
        parser.error('Expected original 1280x720 recording')
    reader = MinimapReader(load_calibration(resolve_calibration_path()))
    args.out.mkdir(parents=True)
    try:
        references = {ref['source_time']: ref for ref in atlas['references']}
        for stamp in range(2, max(references)+1, 2):
            cap.set(cv2.CAP_PROP_POS_MSEC, stamp * 1000)
            ok, frame = cap.read()
            if not ok:
                raise ValueError('Missing calibrated video frame')
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            reader.read(rgb)
            ref = references.get(stamp)
            if ref is None:
                continue
            if reader.last_circle is None:
                raise ValueError('Radar circle not found')
            crop, cx, cy, radius = reader._crop_from_circle(rgb, reader.last_circle)
            yy, xx = np.ogrid[:crop.shape[0], :crop.shape[1]]
            distance = (xx-cx)**2 + (yy-cy)**2
            mask = np.uint8((distance < (radius-8)**2) & (distance > 22**2)) * 255
            saturated = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)[:, :, 1] > 160
            mask[cv2.dilate(np.uint8(saturated), np.ones((7, 7), np.uint8)) > 0] = 0
            crop[mask == 0] = 0
            if not cv2.imwrite(str(args.out/ref['image']), cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)):
                raise OSError('Failed to write atlas crop')
        radar = cv2.imread(str(maps/'radar.png'))
        cv2.imwrite(str(args.out/'walkable.png'), build_mask(radar, regions))
        for name in ('atlas.json', 'navigation.json'):
            (args.out/name).write_bytes((source/name).read_bytes())
    finally:
        cap.release()


if __name__ == '__main__':
    main()
