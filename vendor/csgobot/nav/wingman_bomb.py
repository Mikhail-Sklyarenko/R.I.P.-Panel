"""Planted-C4 radar candidate, independent of the occluded player arrow.

Only a fresh CT/planted game state enables this sensor. A unique compact C4
glyph must register to the same site position across three separate frames.
The result is an approach target, never proof that defusing has started.
"""
from concurrent.futures import ThreadPoolExecutor
import logging
import math
import cv2
import numpy as np
from nav.dense_localizer import DenseMapMatcher
from nav.radar_geom import detect_radar_circle
from nav.hud_mask import exclude_range_ring


class BombReader:
    def __init__(self,map_rgb,*,scale=.355,site_bounds=(800,640,885,760),inferno_hud=True,hud_map_id=None):
        self.matcher=DenseMapMatcher(map_rgb,translucent=True,inferno_hud=inferno_hud)
        self.hud_matcher=None
        if hud_map_id is not None:
            from nav.hud_atlas_matcher import HudAtlasMatcher
            self.hud_matcher=HudAtlasMatcher(hud_map_id,map_rgb.shape[:2])
        self.site_bounds=tuple(site_bounds)
        if len(self.site_bounds)!=4 or not all(math.isfinite(v) for v in self.site_bounds):
            raise ValueError("Invalid bomb bounds")
        x1,y1,x2,y2=self.site_bounds
        if not 0<=x1<x2<map_rgb.shape[1] or not 0<=y1<y2<map_rgb.shape[0]:
            raise ValueError("Bomb bounds outside map")
        self.scale=scale

    @staticmethod
    def glyphs(rgb,cx,cy,radius):
        r,g,b=rgb.astype(np.int16).transpose(2,0,1)
        yy,xx=np.ogrid[:rgb.shape[0],:rgb.shape[1]]
        mask=np.uint8((r>150)&(r-g>75)&(r-b>60)&
                      ((xx-cx)**2+(yy-cy)**2<(radius-12)**2))
        count,labels,stats,centers=cv2.connectedComponentsWithStats(mask)
        points=[]
        for i in range(1,count):
            x,y,w,h,area=stats[i]
            # Radar enemies are round/arrow-shaped; C4 is a filled rectangle.
            if 8<=w<=16 and 6<=h<=12 and 1.15<=w/h<=2 and area/(w*h)>=.75:
                points.append(tuple(centers[i]))
        return points

    def read(self,image):
        circle=detect_radar_circle(image)
        if circle is None:return None
        x,y,w,h=circle.rect;rgb=image[y:y+h,x:x+w]
        if rgb.shape[:2]!=(h,w):return None
        cx,cy=circle.cx-x,circle.cy-y;radius=circle.radius
        points=self.glyphs(rgb,cx,cy,radius)
        if len(points)!=1:return None
        yy,xx=np.ogrid[:h,:w];distance=(xx-cx)**2+(yy-cy)**2
        mask=np.uint8((distance<(radius-7)**2)&(distance>22**2))*255
        color=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)[:,:,1]>160
        mask[cv2.dilate(np.uint8(color),np.ones((7,7),np.uint8))>0]=0
        exclude_range_ring(mask,cx,cy,radius)
        registration=self.matcher.match_at_scale(rgb,mask,self.scale)
        if registration is None and self.hud_matcher is not None:
            registration=self.hud_matcher.match_at_scale(rgb,mask,self.scale)
        if registration is None:return None
        point=registration[0]@np.array([*points[0],1.])
        left,top,right,bottom=self.site_bounds
        if not left<=point[0]<=right or not top<=point[1]<=bottom:return None
        return tuple(float(v) for v in point)


class BombTracker:
    def __init__(self,reader):
        self.reader=reader
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='wingman-bomb')
        self.future=None
        self.context=None
        self.generation=0
        self.point=None
        self.candidate=None
        self.count=0
        self.next_at=0.

    def update(self,image,*,context,now):
        if context!=self.context:
            self.context=context;self.generation+=1
            self.point=self.candidate=None;self.count=0;self.next_at=0.
        if self.future is not None and self.future.done():
            job=self.future;self.future=None
            try:generation,stamp,point=job.result()
            except Exception:
                logging.getLogger('CS2Bot.wingman').exception('bomb_observation_failed')
                generation,stamp,point=-1,now,None
            if generation==self.generation and context is not None and 0<=now-stamp<=.6:
                self.accept(point)
        if context is not None and self.point is None and self.future is None and now>=self.next_at:
            self.next_at=now+.25;generation=self.generation;frame=image.copy()
            self.future=self.executor.submit(lambda:(generation,now,self.reader.read(frame)))
        return self.point

    def accept(self,point):
        if point is None:self.candidate=None;self.count=0;return
        if self.candidate is None or math.dist(point,self.candidate)>8:
            self.candidate=point;self.count=1
        else:
            self.count+=1
            self.candidate=tuple((a*(self.count-1)+b)/self.count for a,b in zip(self.candidate,point))
        if self.count>=3:self.point=tuple(round(v) for v in self.candidate)

    def close(self):
        self.executor.shutdown(wait=False,cancel_futures=True)
