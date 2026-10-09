#!/usr/bin/env python3
"""Rebuild both Vertigo floors from versioned RGBA sources and the original video.

Writes to a NEW directory, never overwrites an installed/user profile.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor/csgobot'))
from nav.calibration import load_calibration
from nav.minimap_reader import MinimapReader
from nav.paths import resolve_calibration_path
from nav.hud_mask import exclude_range_ring


def composite_radar(rgba):
    if rgba is None or rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError('Expected the original RGBA radar')
    return np.uint8(rgba[:,:,:3].astype(float)*(rgba[:,:,3:4]/255))


def build_mask(radar, layer, portals, geometry_edits=()):
    h,s,v=cv2.split(cv2.cvtColor(radar,cv2.COLOR_BGR2HSV))
    if layer=='upper':
        floor=(h>=14)&(h<=42)&(s>=40)&(v>=55)&(v<=108)
    elif layer=='lower':
        floor=(h>=120)&(s>=35)&(v>=38)&(v<=100)
        floor|=(h>=5)&(h<=42)&(s>=40)&(v>=50)&(v<=108)
    else:
        raise ValueError('Unknown floor')
    # Coloured buy/site outlines are annotations, not impassable thin walls.
    floor|=(h>=35)&(h<=85)&(s>=60)&(v>=65)&(v<=195)
    floor|=(h>=5)&(h<=32)&(s>=90)&(v>=65)&(v<=195)
    mask=np.uint8(floor)*255
    allowed=np.zeros_like(mask)
    cv2.fillPoly(allowed,[np.array([(125,160),(630,160),(630,380),(815,400),(815,827),(445,861),(143,827),(140,540),(120,485)])],255)
    mask &= allowed
    # Deliberately exclude the ladder shaft; it is not a walking portal.
    cv2.rectangle(mask,(447,596),(500,649),0,-1)
    # Inspected continuous ramp surface and its solid obstruction.
    cv2.fillPoly(mask,[np.array([(548,576),(649,576),(701,655),(701,815),(560,815)])],255)
    cv2.rectangle(mask,(635,635),(689,697),0,-1)
    cv2.fillPoly(mask,[np.array([(163,390),(246,390),(246,514),(163,514)])],255)
    for portal in portals:
        cv2.polylines(mask,[np.array(portal['upper_to_lower'],np.int32)],False,255,20)
    for edit in geometry_edits:
        if layer not in edit['layers']:continue
        points=np.array(edit['points'],np.int32)
        if edit['action']=='block_polygon':cv2.fillPoly(mask,[points],0)
        elif edit['action']=='add_capsule':
            cv2.polylines(mask,[points],False,255,2*int(edit['radius']))
            for point in points:cv2.circle(mask,tuple(point),int(edit['radius']),255,-1)
        else:raise ValueError('Unknown geometry correction')
    count,labels,stats,_=cv2.connectedComponentsWithStats(mask,connectivity=4)
    for i in range(1,count):
        if stats[i,4]<150:mask[labels==i]=0
    return mask


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():parser.error('Output must be a new directory')
    profiles=ROOT/'resources/nav/profiles';maps=ROOT/'resources/nav/maps'
    layers=json.loads((profiles/'de_vertigo/layers.json').read_text())
    manifests={layer:json.loads((profiles/mid/'atlas.json').read_text()) for layer,mid in layers['layers'].items()}
    digest=hashlib.sha256(args.video.read_bytes()).hexdigest()
    if any(a['source_sha256']!=digest for a in manifests.values()):parser.error('Recording hash mismatch')
    cap=cv2.VideoCapture(str(args.video))
    if not cap.isOpened() or (cap.get(3),cap.get(4))!=(1280,720):parser.error('Expected original 1280x720 recording')
    args.out.mkdir(parents=True)
    try:
        for layer,mid in layers['layers'].items():
            destination=args.out/mid;destination.mkdir()
            metadata=json.loads((maps/mid/'meta.json').read_text())
            source=maps/mid/'source_radar.png'
            if hashlib.sha256(source.read_bytes()).hexdigest()!=metadata['source_sha256']:
                raise ValueError('Original radar changed')
            radar=composite_radar(cv2.imread(str(source),cv2.IMREAD_UNCHANGED))
            cv2.imwrite(str(destination/'radar.png'),radar)
            cv2.imwrite(str(destination/'walkable.png'),build_mask(radar,layer,layers['portals'],layers.get('geometry_edits',())))
            atlas=manifests[layer];refs={x['source_time']:x for x in atlas['references']}
            reader=MinimapReader(load_calibration(resolve_calibration_path()))
            for t in range(2,max(refs)+1,2):
                cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,frame=cap.read()
                if not ok:raise ValueError('Missing video frame')
                rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB);reader.read(rgb)
                if t not in refs:continue
                crop,cx,cy,r=reader._crop_from_circle(rgb,reader.last_circle)
                yy,xx=np.ogrid[:crop.shape[0],:crop.shape[1]];d=(xx-cx)**2+(yy-cy)**2
                mask=np.uint8((d<(r-8)**2)&(d>22**2))*255
                mask[cv2.dilate(np.uint8(cv2.cvtColor(crop,cv2.COLOR_RGB2HSV)[:,:,1]>160),np.ones((7,7),np.uint8))>0]=0
                exclude_range_ring(mask,cx,cy,r);crop[mask==0]=0
                cv2.imwrite(str(destination/refs[t]['image']),cv2.cvtColor(crop,cv2.COLOR_RGB2BGR))
            for name in ('atlas.json','navigation.json'):
                (destination/name).write_bytes((profiles/mid/name).read_bytes())
        (args.out/'de_vertigo/layers.json').write_bytes((profiles/'de_vertigo/layers.json').read_bytes())
    finally:cap.release()


if __name__=='__main__':main()
