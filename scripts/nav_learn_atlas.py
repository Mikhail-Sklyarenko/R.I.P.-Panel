#!/usr/bin/env python3
"""Calibrate additional HUD references from original atlas matches only.

Output is a candidate profile. Training-frame coverage is never validation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import math
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor/csgobot'))
import cv2
import numpy as np
from nav.calibration import load_calibration
from nav.minimap_reader import MinimapReader
from nav.paths import resolve_calibration_path,resolve_visual_profile_file
from nav.visual_localizer import VisualLocalizer


def learn(video_path,destination,seconds):
    destination=Path(destination)
    if destination.exists():raise ValueError('Output must be a new directory')
    capture=cv2.VideoCapture(str(video_path));fps=capture.get(cv2.CAP_PROP_FPS)
    if not capture.isOpened() or fps<=0 or (capture.get(3),capture.get(4))!=(1280,720):
        capture.release();raise ValueError('Expected a readable 1280x720 video')
    original=resolve_visual_profile_file('de_dust2','atlas.json').parent
    atlas=json.loads((original/'atlas.json').read_text())
    reader=MinimapReader(load_calibration(resolve_calibration_path()))
    localizer=VisualLocalizer('de_dust2')
    collected=[];patches=[]
    try:
        for index in range(int(seconds*fps)):
            ok,frame=capture.read()
            if not ok:break
            if index%max(1,round(fps))!=0:continue
            stamp=index/fps;rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
            icon=reader.read(rgb)
            if not icon.valid or reader.last_circle is None:continue
            crop,cx,cy,radius=reader._crop_from_circle(rgb,reader.last_circle)
            yy,xx=np.ogrid[:crop.shape[0],:crop.shape[1]]
            distance=(xx-cx)**2+(yy-cy)**2
            mask=np.uint8((distance<(radius-8)**2)&(distance>22**2))*255
            saturated=cv2.cvtColor(crop,cv2.COLOR_RGB2HSV)[:,:,1]>160
            mask[cv2.dilate(np.uint8(saturated),np.ones((7,7),np.uint8))>0]=0
            reg=localizer.register(crop,mask)
            if reg is None or reg.confidence<.8 or reg.inliers<14 or reg.source=='radar':continue
            ref,to_map=localizer._reference_images.get(reg.source,(None,None))
            if ref is None:continue
            inv=cv2.invertAffineTransform(to_map)
            trans=np.column_stack((inv[:,:2]@reg.matrix[:,:2],inv[:,:2]@reg.matrix[:,2]+inv[:,2]))
            agreement=localizer._edge_agreement(crop,mask,trans,ref)
            if agreement is None or agreement<.8:continue
            center=reg.matrix@np.array([cx,cy,1.]);angle=math.degrees(math.atan2(reg.matrix[1,0],reg.matrix[0,0]))
            if any(np.linalg.norm(center-p)<25 and abs((angle-a+180)%360-180)<30 for p,a in patches):continue
            name=f'video_anchor_{len(collected):03d}.png';clean=crop.copy();clean[mask==0]=0
            patches.append((center,angle));collected.append((clean,{'image':name,'to_map':reg.matrix.tolist(),
                'source_video':Path(video_path).name,'source_time':stamp,'parent_reference':reg.source,
                'wall_agreement':agreement,'inliers':reg.inliers}))
            print(f'Anchor {len(collected)} at {stamp:.1f}s',flush=True)
            if len(collected)>=48:break
    finally:capture.release()
    if not collected:raise ValueError('No independently matched high-confidence anchors; output not created')
    destination.mkdir(parents=True)
    for item in atlas['references']:shutil.copy2(original/item['image'],destination/item['image'])
    for crop,item in collected:
        cv2.imwrite(str(destination/item['image']),cv2.cvtColor(crop,cv2.COLOR_RGB2BGR));atlas['references'].append(item)
    atlas['training']={'video':Path(video_path).name,'seconds':seconds,'new_anchors':len(collected),
                       'live_validated':False,'note':'Original atlas and independent wall checks; no chained self-training'}
    (destination/'atlas.json').write_text(json.dumps(atlas,indent=2))
    return atlas['training']

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--video',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--seconds',type=float,default=120)
    a=p.parse_args()
    if not 0<a.seconds<=600:p.error('seconds must be 0–600')
    print(json.dumps(learn(a.video,a.out,a.seconds),indent=2))
