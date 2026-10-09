"""Mirage's overlapping underpass: current HUD label plus measured map position."""
from pathlib import Path
from types import SimpleNamespace
import json
import math
import cv2
import numpy as np
from nav.paths import resolve_visual_profile_file
from nav.walkable import WalkableMap, read_grayscale
from nav.roaming import RoamingGoals


def label_mask(rgb):
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY).astype(np.float32)
    color=(rgb[:,:,0].astype(float)>130)&(rgb[:,:,1]>100)&(rgb[:,:,2]<195)&(rgb[:,:,1].astype(float)>rgb[:,:,2].astype(float)*1.18)
    detail=gray-cv2.GaussianBlur(gray,(0,0),2)
    return np.uint8(color&(detail>5))*255


class MirageLevels:
    def __init__(self):
        path=resolve_visual_profile_file('de_mirage','layers.json')
        self.config=json.loads(path.read_text(encoding='utf-8'))
        if self.config.get('map_id')!='de_mirage':raise ValueError('Mirage layers mismatch')
        self.lower_mask=read_grayscale(path.parent/self.config['layers']['lower'])
        self.near_lower=cv2.dilate(self.lower_mask,np.ones((25,25),np.uint8))>0
        self.templates=[(r['layer'],read_grayscale(path.parent/r['image'])) for r in self.config['labels']]
        self.last_layer=None
        self.last_point=None
        self.last_seen=float('-inf')
        self.label_scores={}

    def reset(self):
        self.last_layer=None
        self.last_point=None
        self.last_seen=float("-inf")

    def read_label(self,frame):
        x0,y0,x1,y1=self.config['label_roi']
        if frame.shape[:2]!=(720,1280):return None
        current=label_mask(frame[y0:y1,x0:x1])
        scores={'upper':0.,'lower':0.}
        for layer,template in self.templates:
            if template.shape[0]>current.shape[0] or template.shape[1]>current.shape[1]:continue
            score=float(cv2.minMaxLoc(cv2.matchTemplate(current,template,cv2.TM_CCOEFF_NORMED))[1])
            if math.isfinite(score):scores[layer]=max(scores[layer],score)
        self.label_scores=scores
        best=max(scores,key=scores.get);other='upper' if best=='lower' else 'lower'
        threshold,margin=(.72,.06) if best=='lower' else (.62,.20)
        return best if scores[best]>=threshold and scores[best]-scores[other]>=margin else None

    def classify(self,frame,point,now):
        xy=np.asarray(point,float)*1023
        if not np.isfinite(xy).all() or not 0<=xy[0]<1024 or not 0<=xy[1]<1024:return None
        x,y=np.rint(xy).astype(int)
        label=self.read_label(frame)
        if not self.near_lower[y,x]:
            # A contradictory label is not permission to drive an unrelated XY.
            layer=None if label=='lower' else 'upper'
        elif label is not None:
            layer=label
        elif (self.last_layer is not None and 0<=now-self.last_seen<=.5
                and self.last_point is not None and np.linalg.norm(xy-self.last_point)<=80*(now-self.last_seen)+4):
            return self.last_layer
        else:layer=None
        if layer is not None:
            self.last_layer,self.last_point,self.last_seen=layer,xy,now
        return layer


def load_grounds(config):
    if config.get('map_id')!='de_mirage':raise ValueError('Mirage layers mismatch')
    folder=resolve_visual_profile_file('de_mirage','layers.json').parent
    baseline=WalkableMap.load('de_mirage')  # Verify the versioned radar hash too.
    if baseline is None:raise ValueError('Missing Mirage surface profile')
    masks={name:read_grayscale(folder/file) for name,file in config['layers'].items()}
    if set(masks)!={'upper','lower'} or any(m.shape!=(baseline.height,baseline.width) for m in masks.values()):
        raise ValueError('Mirage layer dimensions mismatch')
    return {name:WalkableMap(mask,clearance_px=config['clearance_px'],
                grid_step=4 if name=='upper' else config['grid_step']) for name,mask in masks.items()}


class MirageRoamingGoals(RoamingGoals):
    def __init__(self,ground,layer,config):
        super().__init__(ground)
        self.layer,self.config=layer,config
        self.last_portal_at=0.

    def choose(self,point,now=0.):
        if self.layer=='lower' or now-self.last_portal_at>=35.:
            options=[]
            exits=self.config['lower_exits'] if self.layer=='lower' else self.config['upper_entries']
            for exit in exits:
                target=self.ground.norm(exit['point']);path=self.ground.plan(point,target)
                if path:
                    length=sum(math.dist(self.ground.pixel(a),self.ground.pixel(b)) for a,b in zip(path,path[1:]))
                    options.append((length,exit['id'],target,path))
            if options:
                # Traverse toward the opposite end; do not mill around in a
                # narrow lower corridor. Surface approaches pick the nearest.
                _,name,target,path=(max(options) if self.layer=='lower' else min(options))
                self.last_portal_at=now
                return SimpleNamespace(id='underpass_'+name,x=target[0],y=target[1],arrive_radius=.006),path
        return super().choose(point,now)
