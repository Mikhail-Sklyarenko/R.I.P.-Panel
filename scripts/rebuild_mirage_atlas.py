#!/usr/bin/env python3
"""Recreate calibrated HUD crops from the supplied Mirage video and atlas manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'vendor/csgobot'))
import cv2
import numpy as np
from nav.calibration import load_calibration
from nav.minimap_reader import MinimapReader
from nav.paths import resolve_calibration_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists(): parser.error('Output must be a new directory')
    manifest = ROOT/'resources/nav/profiles/de_mirage/atlas.json'
    atlas = json.loads(manifest.read_text())
    if hashlib.sha256(args.video.read_bytes()).hexdigest() != atlas["source_sha256"]:
        parser.error("Video fingerprint differs from the calibrated recording")
    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened() or (cap.get(3),cap.get(4)) != (1280,720):
        parser.error('Expected the original 1280x720 Mirage recording')
    reader = MinimapReader(load_calibration(resolve_calibration_path()))
    args.out.mkdir(parents=True)
    try:
        for ref in atlas['references']:
            cap.set(cv2.CAP_PROP_POS_MSEC,ref['source_time']*1000)
            ok,frame=cap.read()
            if not ok:raise ValueError('Recording ended before calibrated frame')
            rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB);reader.read(rgb)
            if reader.last_circle is None:raise ValueError('Calibrated radar not found')
            crop,cx,cy,radius=reader._crop_from_circle(rgb,reader.last_circle)
            yy,xx=np.ogrid[:crop.shape[0],:crop.shape[1]]
            if ref.get('automated_wall_gate_passed') is False:
                cx,cy=crop.shape[1]/2,crop.shape[0]/2
                radius=min(crop.shape[:2])/2
            d=(xx-cx)**2+(yy-cy)**2
            mask=np.uint8((d<(radius-8)**2)&(d>22**2))*255
            sat=cv2.cvtColor(crop,cv2.COLOR_RGB2HSV)[:,:,1]>160
            if ref.get('automated_wall_gate_passed') is not False:
                sat=cv2.dilate(np.uint8(sat),np.ones((7,7),np.uint8))>0
            mask[sat]=0;crop[mask==0]=0
            if not cv2.imwrite(str(args.out/ref['image']),cv2.cvtColor(crop,cv2.COLOR_RGB2BGR)):
                raise OSError('Cannot write atlas crop')
        (args.out/'atlas.json').write_text(json.dumps(atlas,indent=2))
    finally:cap.release()

if __name__=='__main__':main()
