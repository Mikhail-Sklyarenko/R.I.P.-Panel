"""Measured map-local actions sharing navigation's expiring input lease."""
from __future__ import annotations
import json
import math
import cv2
import numpy as np
from nav.paths import resolve_visual_profile_file


class TraversalActions:
    def __init__(self, zones=()):
        from nav.door_actions import DoorActions
        zones=list(zones)
        self.doors=DoorActions(z for z in zones if z.get("action")=="use_door")
        self.zones = []
        self.active = set()
        self.jump_entries = {}
        self.jump_only = set()
        self._jump = None
        self._attempts = {}
        self._last_jump = {}
        self._stall = {}
        self._stall_delay = {}
        for zone in zones:
            if zone.get('action')=='use_door':continue
            points = self._polygon(zone['polygon'])
            if zone.get('action') not in ('crouch','jump'):
                raise ValueError('Invalid traversal action')
            name = zone['id']
            delay=float(zone.get('min_stall_sec',0.))
            if not math.isfinite(delay) or not 0<=delay<=2:raise ValueError('Invalid traversal stall delay')
            if delay:self._stall_delay[name]=delay
            if zone.get('action')=='jump':self.jump_only.add(name)
            self.zones.append((name,points))
            entry = zone.get('jump_entry')
            if entry is not None:
                polygon = self._polygon(entry['polygon'])
                direction = float(entry['direction_deg'])
                if not math.isfinite(direction):raise ValueError('Invalid jump direction')
                self.jump_entries[name] = (polygon,direction)

    @staticmethod
    def _polygon(value):
        points = np.asarray(value,dtype=np.float32)
        if (points.ndim != 2 or points.shape[1] != 2 or len(points) < 3
                or not np.isfinite(points).all() or np.any(points<0)
                or np.any(points>1) or cv2.contourArea(points) <= 0):
            raise ValueError('Invalid traversal zone')
        return points

    @classmethod
    def load(cls,map_id):
        path = resolve_visual_profile_file(map_id,'traversal.json')
        if not path.is_file():return cls()
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('map_id') != map_id:raise ValueError('Traversal map mismatch')
        return cls(data.get('zones',()))

    @property
    def phase(self):
        if self.doors.phase!="goal":return self.doors.phase
        if self._jump is not None:return "jump" if self._jump[0] in self.jump_only else "jump_crouch"
        return "crouch_passage" if self.active-self.jump_only else "goal"

    def reset(self):
        self.doors.reset()
        self.active.clear()
        self._stall.clear()
        self._jump = None
        # Input loss must not reset the attempt budget and cause repeated hops.
        # Leaving the passage or loading a new map starts a new attempt budget.

    def apply(self,keys,point,*,now=None,yaw=None,target=None,observation=None):
        result=self.doors.apply(keys,point,now=now,yaw=yaw,target=target,observation=observation)
        if not result & {'w','a','s','d'} or point is None:
            self.reset()
            return result
        point=tuple(map(float,point))
        active=set()
        for name,polygon in self.zones:
            distance=cv2.pointPolygonTest(polygon,point,True)
            if distance >= (-3/1023 if name in self.active else 0):active.add(name)
            if distance < -32/1023:
                self._attempts.pop(name,None)
                if self._jump is not None and self._jump[0]==name:self._jump=None
            entry=self.jump_entries.get(name)
            if entry is None or now is None or yaw is None:continue
            if not all(math.isfinite(v) for v in (now,yaw)):continue
            forward=int('w' in result)-int('s' in result)
            right=int('d' in result)-int('a' in result)
            if not (forward or right):continue
            movement=yaw+math.degrees(math.atan2(right,forward))
            error=(movement-entry[1]+180)%360-180
            stalled=True
            if name in self._stall_delay:
                previous=self._stall.get(name)
                if (previous is None or now<previous[1]
                        or math.dist(point,previous[0])*1023>2
                        or cv2.pointPolygonTest(entry[0],point,False)<0):
                    self._stall[name]=(point,now)
                    stalled=False
                else:stalled=now-previous[1]>=self._stall_delay[name]
            # Only the outside-to-inside approach requires a jump. A reverse
            # traversal, a turn in place, or a distant waypoint cannot trigger it.
            if (stalled and self._jump is None and abs(error)<=30
                    and cv2.pointPolygonTest(entry[0],point,False)>=0
                    and self._attempts.get(name,0)<2
                    and now-self._last_jump.get(name,float('-inf'))>=1.2):
                self._jump=(name,now)
                self._last_jump[name]=now
                self._attempts[name]=self._attempts.get(name,0)+1
        self.active=active
        if active-self.jump_only:result.add('ctrl')
        if self._jump is not None:
            name,started=self._jump
            elapsed=(now-started) if now is not None else float('inf')
            if 0<=elapsed<.22:
                result.add('space')
                if name not in self.jump_only:
                    if elapsed<.06:result.discard('ctrl')
                    else:result.add('ctrl')
            elif .22<=elapsed<1.2:
                if name not in self.jump_only:result.add('ctrl')
            else:self._jump=None
        return result
