"""Reachable, persistent Wingman missions; no input or enemy position guessing."""
from collections import Counter, deque
from dataclasses import dataclass
import math
import random


@dataclass(frozen=True)
class Mission:
    point: tuple
    action: str = 'patrol'


class MissionPlanner:
    def __init__(self, catalog, *, rng=None):
        self.catalog = catalog
        self.rng = rng or random.Random()
        self.visits = Counter()
        self.recent = deque(maxlen=3)
        self.last_plant = None
        self.last_approach = None
        self.entry_visits = Counter()
        self.last_entry = None
        self.bomb_point = None
        self.reset_round()

    def reset_round(self):
        self.role = None
        self.queue = deque()
        self.searched = set()
        self.failed = set()

    @staticmethod
    def role_for(team, bomb):
        if team == 'CT':return 'defuse' if bomb == 'planted' else 'patrol'
        return 'plant' if bomb == 'carried_self' else ('guard' if bomb == 'planted' else 'support')

    def _length(self, ground, path):
        return sum(math.dist(ground.pixel(a),ground.pixel(b)) for a,b in zip(path,path[1:]))

    def choose(self, ground, start, *, team, bomb, incoming=None):
        role = self.role_for(team,bomb)
        if role != self.role:
            self.queue.clear()
            self.searched.clear()
            self.failed.clear()
            self.role = role
        if self.queue:return self.queue[0]
        key = {'plant':'plant_points','defuse':'search_points','patrol':'patrol_points',
               'guard':'guard_points','support':'approach_points'}[role]
        candidates = [tuple(p) for p in self.catalog.get(key,self.catalog.get('search_points',()))]
        candidates = [p for p in candidates if p not in self.failed and ground.contains(ground.norm(p))]
        if role == 'defuse':
            if self.bomb_point is not None:
                x,y=self.bomb_point
                near=[(x+dx,y+dy) for dx,dy in ((0,0),(-6,0),(6,0),(0,-6),(0,6))]
                near=[p for p in near if p not in self.failed and p not in self.searched
                      and ground.contains(ground.norm(p))]
            else:near=[]
            fresh = [p for p in candidates if p not in self.searched]
            if not fresh:self.searched.clear();fresh=candidates
            ranked = near+sorted(fresh,key=lambda p:math.dist(ground.pixel(start),p))
        else:
            distant = [p for p in candidates if math.dist(ground.pixel(start),p) >= (28 if role != 'plant' else 0)]
            if distant:candidates=distant
            # Keep previously used points as a fallback if all alternatives are
            # disconnected by a newly observed obstacle.
            def score(p):
                repeat = p == self.last_plant if role == 'plant' else p in self.recent
                backtrack = False
                if incoming is not None and role in ('patrol','support','guard'):
                    x,y=ground.pixel(start);dx,dy=p[0]-x,p[1]-y
                    length=math.hypot(dx,dy)*math.hypot(*incoming)
                    backtrack=length>1 and (dx*incoming[0]+dy*incoming[1])/length < -.3
                return (repeat,backtrack,self.visits[p]*2+self.rng.random())
            ranked = sorted(candidates,key=score)
        for point in ranked:
            route = ground.plan(start,ground.norm(point))
            if not route:continue
            if role == 'plant':
                self.last_plant = point
                # Explicit alternative entries represent different connected
                # corridors, not random plant coordinates on one shortest path.
                entries=self.catalog.get('entry_routes',{})
                box=self.catalog.get('entry_route_box')
                sx,sy=ground.pixel(start)
                if entries and box and box[0]<=sx<=box[2] and box[1]<=sy<=box[3]:
                    names=list(entries);self.rng.shuffle(names)
                    names.sort(key=lambda n:(self.entry_visits[n],n==self.last_entry))
                    for name in names:
                        stops=[tuple(p) for p in entries[name]]
                        waypoints=[start]+[ground.norm(p) for p in stops]+[ground.norm(point)]
                        if not all(ground.contains(p) for p in waypoints):continue
                        if not all(ground.plan(a,b) for a,b in zip(waypoints,waypoints[1:])):continue
                        self.entry_visits[name]+=1;self.last_entry=name
                        self.queue.extend(Mission(p,'approach') for p in stops)
                        self.queue.append(Mission(point,role))
                        return self.queue[0]
                # Optional staging point must progress toward A without a large detour.
                options = [None]+[tuple(p) for p in self.catalog['approach_points']]
                self.rng.shuffle(options)
                options.sort(key=lambda p:p == self.last_approach)
                direct = self._length(ground,route)
                for via in options:
                    if via is None:
                        self.last_approach=None
                        break
                    if math.dist(ground.pixel(start),via)<30 or math.dist(via,point)<25:continue
                    middle=ground.norm(via)
                    a=ground.plan(start,middle);b=ground.plan(middle,ground.norm(point))
                    if not a or not b:continue
                    la,lb=self._length(ground,a),self._length(ground,b)
                    if la+lb <= direct*1.25+15 and lb < direct-20:
                        self.queue.append(Mission(via,'approach'))
                        self.last_approach=via
                        break
            self.queue.append(Mission(point,role))
            return self.queue[0]
        return None

    def complete(self, *, failed=False):
        if not self.queue:return
        mission=self.queue.popleft()
        self.visits[mission.point]+=1
        self.recent.append(mission.point)
        if mission.action=='defuse':self.searched.add(mission.point)
        if failed:
            self.failed.add(mission.point)
            self.queue.clear()
