#!/usr/bin/env python3
"""Build a radar-derived experimental profile, never a verified full-map claim."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor/csgobot'))
import cv2
import numpy as np
from nav.walkable import WalkableMap


def build(destination):
    radar_path=ROOT/'resources/nav/maps/de_dust2/radar.png'
    radar=cv2.imread(str(radar_path))
    hsv=cv2.cvtColor(radar,cv2.COLOR_BGR2HSV)
    h,s,v=cv2.split(hsv)
    # Colored floor fills only. Neutral structures, bright markings and black
    # unknown space are excluded. No dilation or automatic wall bridging.
    floor=(h>=30)&(h<=110)&(s>=18)&(s<=150)&(v>=45)&(v<=155)
    mask=np.uint8(floor)*255
    # Radar explicitly hatches this multi-level overlap. A 2-D planner cannot
    # distinguish the underpass and upper route; do not invent a connection.
    mask[140:280,610:686]=0
    count,labels,stats,_=cv2.connectedComponentsWithStats(mask,connectivity=4)
    for i in range(1,count):
        if stats[i,cv2.CC_STAT_AREA]<100:mask[labels==i]=0
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    cv2.imwrite(str(destination/'walkable.png'),mask)
    meta={'map_id':'de_dust2','version':'expanded-ground-2','scope':'Dust2 ground routes with connected Long door passages',
          'map_sha256':hashlib.sha256(radar_path.read_bytes()).hexdigest(),'clearance_px':6,'grid_step':2,'search_weight':1.5,
          'experimental':True,'live_validated':False,'full_map_ready':False,
          'mask_source':'colored radar floor, structures excluded; multi-level overlap blocked',
          'limitations':['No height or directed transition model','No independent full-map localization validation','Disconnected areas remain disconnected']}
    (destination/'navigation.json').write_text(json.dumps(meta,indent=2)+'\n')
    ground=WalkableMap(mask,clearance_px=6,grid_step=2,search_weight=1.5)
    _,components,areas,_=cv2.connectedComponentsWithStats(np.uint8(ground.free),connectivity=4)
    report={**meta,'raw_floor_pixels':int((mask>0).sum()),'usable_pixels':int(ground.free.sum()),
            'components_over_100_pixels':int(sum(a[cv2.CC_STAT_AREA]>=100 for a in areas[1:])),
            'atlas_references':len(json.loads((ROOT/'resources/nav/profiles/de_dust2/atlas.json').read_text())['references'])}
    overlay=radar.copy();overlay[ground.free]=(overlay[ground.free]*.45+np.array([70,210,90])*.55).astype(np.uint8)
    cv2.imwrite(str(destination/'preview.png'),overlay)
    (destination/'coverage.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=ROOT/'resources/nav/experimental/de_dust2')
    print(json.dumps(build(p.parse_args().out),indent=2))
