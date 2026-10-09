#!/usr/bin/env python3
"""Rebuild the inspected Mirage floor mask from its versioned radar and regions.
Does not regenerate the independently calibrated visual atlas.
"""
from pathlib import Path
import cv2,numpy as np,json,sys
r=Path(__file__).resolve().parents[1];sys.path.insert(0,str(r/'vendor/csgobot'))
from nav.walkable import WalkableMap
p=r/'resources/nav/profiles/de_mirage';im=cv2.imread(str(r/'resources/nav/maps/de_mirage/radar.png'));h,s,v=cv2.split(cv2.cvtColor(im,cv2.COLOR_BGR2HSV))
base=((h>=75)&(h<=115)&(s>=18)&(s<=140)&(v>=40)&(v<=150))|((h>=5)&(h<=30)&(s>=25)&(s<=135)&(v>=55)&(v<=150))
# Spawn outlines and bombsite outlines are annotations, not physical walls.
base |= ((h>=40)&(h<=85)&(s>=20)&(v>=70)&(v<=185))
definition=json.loads((r/'resources/nav/maps/de_mirage/floor_regions.json').read_text())
import hashlib
if hashlib.sha256((r/'resources/nav/maps/de_mirage/radar.png').read_bytes()).hexdigest()!=definition['map_sha256']:
    raise ValueError('Mirage radar changed: inspect floor regions before rebuilding')
polygons=definition['floor_regions']
for region in polygons:
 zone=np.zeros(h.shape,np.uint8);cv2.fillPoly(zone,[np.array(region['points'],np.int32)],1)
 base|=(zone>0)&(v>=65)&(v<=96)&(s<65)
zone=np.zeros(h.shape,np.uint8);cv2.rectangle(zone,(510,730),(616,830),1,-1)
base|=(zone>0)&(h>=5)&(h<=35)&(s>=45)&(v>=70)&(v<=195)
mask=np.uint8(base)*255
# Never connect these vertical/overlapping shortcuts in a 2-D ground planner.
blocks=definition['blocked_transitions']
for region in blocks:cv2.fillPoly(mask,[np.array(region['points'],np.int32)],0)
n,l,st,_=cv2.connectedComponentsWithStats(mask,connectivity=4)
for i in range(1,n):
 if st[i,4]<100:mask[l==i]=0
cv2.imwrite(str(p/'walkable.png'),mask)
meta=json.loads((p/'navigation.json').read_text());meta['floor_regions']=polygons;meta['blocked_transitions']=blocks;meta['mask_source']='radar floor palette plus inspected A/CT/T floor regions; spawn outlines are annotations';(p/'navigation.json').write_text(json.dumps(meta,indent=2))
w=WalkableMap.load('de_mirage');_,l,s,_=cv2.connectedComponentsWithStats(np.uint8(w.free),connectivity=4)
print(sorted([int(x[4]) for x in s[1:] if x[4]>100],reverse=True))
prev=im.copy();prev[w.free]=(prev[w.free]*.35+np.array([60,220,100])*.65).astype(np.uint8);cv2.imwrite(str(p/'preview.png'),prev)
