"""One use pulse per measured approach, with fresh scene evidence and crossing feedback."""
from dataclasses import dataclass
import math
import cv2
import numpy as np


@dataclass(frozen=True)
class DoorObservation:
    observed_at: float
    map_id: str
    red_panel: bool
    opening_error_deg: float | None = None


def observe_door(frame, map_id, stamp):
    """Inferno red / Nuke orange panel near the crosshair; never locates a door.

    The action additionally requires a calibrated map-local approach, a route
    through that doorway, movement intent, and the camera facing the opening.
    """
    if map_id not in ('de_inferno','de_nuke') or frame.shape[:2] != (720,1280):
        return None
    patch=frame[230:410,490:710]
    h,s,v=cv2.split(cv2.cvtColor(patch,cv2.COLOR_RGB2HSV))
    red=(((h>=10)&(h<=35)&(s>=110)&(v>=55)) if map_id=='de_nuke' else
         (((h<=12)|(h>=172))&(s>=100)&(v>=35)&(v<=220)))
    # Broad central paint, not a small enemy/blood pixel or a distant door.
    opening=None
    if map_id=='de_nuke':
        opening=nuke_opening_error(frame)
    return DoorObservation(stamp,map_id,bool(np.mean(red)>=.72),opening)


def nuke_opening_error(frame):
    """Two tall orange jambs give a heading cue; movement still needs clear ground."""
    h,s,v=cv2.split(cv2.cvtColor(frame,cv2.COLOR_RGB2HSV))
    orange=np.uint8((h>=8)&(h<=30)&(s>=130)&(v>=70))*255
    vertical=cv2.morphologyEx(orange,cv2.MORPH_OPEN,np.ones((45,3),np.uint8))
    _,_,stats,_=cv2.connectedComponentsWithStats(vertical)
    posts=sorted((b for b in stats[1:] if b[3]>=100 and 3<=b[2]<=80 and b[4]>b[3]*2),key=lambda b:b[0])
    candidates=[]
    for a,b in zip(posts,posts[1:]):
        gap=b[0]-(a[0]+a[2]);overlap=min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1])
        if not (40<=gap<=420 and min(a[3],b[3])>=.65*max(a[3],b[3]) and overlap>=.75*min(a[3],b[3])):continue
        center=(a[0]+a[2]+b[0])/2
        candidates.append((overlap,center))
    if not candidates:return None
    _,center=max(candidates)
    return math.degrees(math.atan((center-640)/480.))


class DoorActions:
    def __init__(self,zones=()):
        self.zones=[]
        zones=list(zones)
        self.map_ids=frozenset(z.get("map_id","de_inferno") for z in zones)
        for zone in zones:
            center=np.asarray(zone['center'],float)
            normal=np.asarray(zone['normal'],float)
            reach=float(zone['reach_px'])
            if (center.shape!=(2,) or normal.shape!=(2,)
                    or not np.isfinite(center).all() or not np.isfinite(normal).all()
                    or np.any(center<0) or np.any(center>1)
                    or not .99<=np.linalg.norm(normal)<=1.01
                    or not math.isfinite(reach) or not 2<=reach<=16):
                raise ValueError('Invalid door geometry')
            self.zones.append((zone['id'],center,normal,reach))
        self._used={}
        self._pulse=None
        self._busy_until=0.
        self.phase='goal'

    def reset(self):
        self._pulse=None
        self._busy_until=0.
        self.phase='goal'
        # Loss of input/vision must never generate a second use edge, which
        # could close a door just opened. Rearm only after leaving its vicinity.

    def busy(self,now):
        return now<self._busy_until

    def opening_heading(self,point,*,now,yaw,target,observation):
        if (observation is None or observation.map_id!='de_nuke' or observation.map_id not in self.map_ids or observation.opening_error_deg is None
                or not math.isfinite(observation.opening_error_deg) or abs(observation.opening_error_deg)>60
                or not 0<=now-observation.observed_at<=.25):return None
        p=np.asarray(point,float);q=np.asarray(target,float)
        facing=np.array([math.cos(math.radians(yaw)),math.sin(math.radians(yaw))])
        for _,center,normal,_ in self.zones:
            offset=(p-center)*1023;side=1. if offset@normal>=0 else -1.
            if (np.linalg.norm(offset)<=32 and abs(offset@normal)>=2 and facing@(-side*normal)>=.5
                    and side*float((q-center)@normal)*1023<0):
                return yaw+observation.opening_error_deg
        return None

    def apply(self,keys,point,*,now,yaw,target,observation):
        result=set(keys)
        if point is None or now is None or yaw is None or target is None:
            self.reset();return result
        if not all(math.isfinite(v) for v in (*point,*target,now,yaw)):
            self.reset();return result
        p=np.asarray(point,float)
        for name,center,normal,reach in self.zones:
            if np.linalg.norm((p-center)*1023)>48:
                if name in self._used:
                    self._used.pop(name,None)
                    self.reset()
            if name in self._used:
                side=self._used[name]
                if side*float((p-center)@normal)*1023 < -8:
                    self.phase='door_crossed'
                    self._busy_until=0.
        fresh=(observation is not None and observation.map_id in self.map_ids
               and math.isfinite(observation.observed_at)
               and 0<=now-observation.observed_at<=.25 and observation.red_panel)
        moving=bool(result&{'w','a','s','d'})
        if self._pulse is not None:
            name,started=self._pulse
            if not fresh or not moving:
                self.reset();return result
            if fresh and moving and 0<=now-started<.12:
                result.add('e')
            elif now-started>=.9:
                self._pulse=None
                if self.phase!='door_crossed':self.phase='door_unconfirmed'
            return result
        if not fresh or not moving:return result
        facing=np.array([math.cos(math.radians(yaw)),math.sin(math.radians(yaw))])
        forward=int('w' in result)-int('s' in result)
        right=int('d' in result)-int('a' in result)
        travel=np.array([facing[0]*forward-facing[1]*right,facing[1]*forward+facing[0]*right])
        for name,center,normal,reach in self.zones:
            if name in self._used:continue
            offset=(p-center)*1023
            side=1. if offset@normal>=0 else -1.
            toward=-side*normal
            # Both the planned route and actual key direction must enter the
            # aperture. Looking at a red panel while leaving cannot toggle it.
            if (np.linalg.norm(offset)<=reach and abs(offset@normal)>=2
                    and facing@toward>=.5 and travel@toward>=.5
                    and side*float((np.asarray(target)-center)@normal)*1023<=3):
                self._used[name]=side
                self._pulse=(name,now)
                self._busy_until=now+.9
                self.phase='door_opening'
                result.add('e')
                break
        return result
