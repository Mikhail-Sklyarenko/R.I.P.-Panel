"""Persistent exploration goals with measured visitation and session restrictions."""
from collections import deque
from types import SimpleNamespace
import math
import random
import cv2
import numpy as np


class RoamingGoals:
    def __init__(self, ground, seed=None):
        self.rng = random.Random(seed)
        self.recent = deque(maxlen=24)
        self.visits = {}
        self.serial = 0
        self.set_ground(ground)

    def set_ground(self, ground):
        self.ground = ground
        # Warm immutable edge masks before selecting goals during a live tick.
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
            ground._edge_clear((0,0),(dx,dy))
        _, self.labels = cv2.connectedComponents(np.uint8(ground.grid), connectivity=4)
        self._candidates = {}

    def observe(self, point, now):
        pixel = self.ground.pixel(point)
        self.visits[(int(pixel[0]//32), int(pixel[1]//32))] = now
        if len(self.visits)>2048:
            self.visits = {k:v for k,v in self.visits.items() if now-v<180}

    def choose(self, point, now=0.):
        ground = self.ground
        start = ground._attach(point)
        if start is None:
            return None
        component = int(self.labels[start[1],start[0]])
        if component not in self._candidates:
            ys,xs = np.nonzero(self.labels == component)
            self._candidates[component] = list(zip(xs.tolist(),ys.tolist()))
        candidates = self._candidates[component]
        if len(candidates)>160:
            candidates = self.rng.sample(candidates,160)
        origin = ground.pixel(point)
        extent = max((math.dist(origin,(x*ground.step,y*ground.step)) for x,y in candidates), default=0.)
        minimum = min(100., extent*.45)
        ranked = []
        for x,y in candidates:
            pixel = (x*ground.step,y*ground.step)
            distance = math.dist(pixel,origin)
            if distance<max(16.,minimum):
                continue
            novelty = min((math.dist(pixel,old) for old in self.recent),default=240.)
            visit = self.visits.get((int(pixel[0]//32),int(pixel[1]//32)))
            penalty = max(0.,120.-(now-visit))*2 if visit is not None else 0.
            clearance = float(ground.clearance[pixel[1],pixel[0]])
            score = min(novelty,240.) - abs(distance-min(260.,extent))*.2 - penalty + min(clearance,20.)*2 + self.rng.uniform(0,8)
            ranked.append((score,ground.norm(pixel)))
        for _,target in sorted(ranked,reverse=True)[:8]:
            path = ground.plan(point,target)
            if path:
                self.recent.append(ground.pixel(target))
                self.serial += 1
                return SimpleNamespace(id=f'roam_{self.serial}',x=target[0],y=target[1],arrive_radius=.009),path
        return None
