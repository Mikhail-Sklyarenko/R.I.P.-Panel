"""Cache roof spawn: positively identified raised surface, one-way drop exit.

Ground routes retain the solid roof footprint. A current HUD label is required
inside it; proximity or a planned route never establishes elevation.
"""
import json
import math
from types import SimpleNamespace
import cv2
from nav.paths import resolve_visual_profile_file
from nav.walkable import WalkableMap, read_grayscale
import numpy as np
from nav.roaming import RoamingGoals


def label_mask(rgb):
    # Isolate yellow lettering by chroma rather than a maximum blue value:
    # glare brightens every channel without erasing the yellow difference.
    v=rgb.astype(np.int16)
    yellow=(v[:,:,0]>150)&(v[:,:,1]>130)&(v[:,:,0]-v[:,:,2]>20)&(v[:,:,1]-v[:,:,2]>12)
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY).astype(np.float32)
    detail=gray-cv2.GaussianBlur(gray,(0,0),2)
    return np.uint8(yellow&(detail>3))*255


class CacheLevels:
    def __init__(self):
        path=resolve_visual_profile_file('de_cache','layers.json')
        self.config=json.loads(path.read_text(encoding='utf-8'))
        if self.config.get('map_id')!='de_cache':raise ValueError('Cache layers mismatch')
        self.templates=[read_grayscale(path.parent/r['image']) for r in self.config['labels']]
        if not self.templates or any(t.shape[0]>29 or t.shape[1]>240 or np.count_nonzero(t)<30 for t in self.templates):
            raise ValueError('Invalid Cache roof label templates')

    def classify(self,frame,point,now):
        x,y=point[0]*1023,point[1]*1023
        if not all(math.isfinite(v) for v in (x,y)) or not (0<=x<1024 and 0<=y<1024):return None
        x0,y0,x1,y1=self.config['roof_bounds']
        if not (x0<=x<=x1 and y0<=y<=y1):
            # The north landing is ordinary ground. No roof state can leak into
            # another spawn; this classifier keeps no stale floor memory.
            return 'upper'
        if frame.shape[:2]!=(720,1280):return None
        a,b,c,d=self.config['label_roi']
        current=label_mask(frame[b:d,a:c])
        for template in self.templates:
            score=float(cv2.minMaxLoc(cv2.matchTemplate(current,template,cv2.TM_CCOEFF_NORMED))[1])
            if math.isfinite(score) and score>=.64:return 'roof'
        return None


def load_grounds(config):
    if config.get('map_id')!='de_cache':raise ValueError('Cache layers mismatch')
    folder=resolve_visual_profile_file('de_cache','layers.json').parent
    ground=WalkableMap.load('de_cache')
    mask=read_grayscale(folder/config['layers']['roof'])
    if ground is None or mask.shape!=(ground.height,ground.width):raise ValueError('Cache roof dimensions mismatch')
    return {'upper':ground,'roof':WalkableMap(mask,clearance_px=config['clearance_px'],grid_step=config['grid_step'])}


class CacheRoamingGoals(RoamingGoals):
    def __init__(self,ground,layer,config):
        super().__init__(ground)
        self.layer,self.config=layer,config

    def choose(self,point,now=0.):
        if self.layer!='roof':return super().choose(point,now)
        target=self.ground.norm(self.config['exit_point'])
        path=self.ground.plan(point,target)
        if path:
            return SimpleNamespace(id='roof_drop_north',x=target[0],y=target[1],arrive_radius=.004),path
        return None
