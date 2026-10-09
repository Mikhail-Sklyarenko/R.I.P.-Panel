"""Recorded T-side approaches, committed until a measured A-side exit.

Apartment geometry is usable only after entry from T, never as general floor
connectivity or a reverse route from A. Round resets invalidate the commitment.
"""
from collections import Counter
from pathlib import Path
import json
import math
import random
from nav.walkable import WalkableMap,read_grayscale
from nav.pack import NavGoal
from nav.traversal_actions import TraversalActions


class WingmanIngress:
    def __init__(self, folder, *, rng=None):
        self.folder=Path(folder)
        self.data=json.loads((self.folder/'ingress.json').read_text())
        self.rng=rng or random.Random()
        self.counts=Counter()
        self.previous=None
        self.routes={}
        for route in self.data['routes']:
            ground=WalkableMap(read_grayscale(self.folder/route['mask']),clearance_px=4,grid_step=2)
            points=tuple(ground.norm(p) for p in route['points'])
            if not all(ground.contains(p) for p in points) or not all(ground.visible(a,b) for a,b in zip(points,points[1:])):
                raise ValueError('Invalid recorded ingress: '+route['id'])
            self.routes[route['id']]=(route,ground,points)
        self.reset_round()

    def reset_round(self):
        self.active=None
        self.used=False
        self.base=None
        self.stage=0
        self.retreating=False
        self.blocked_at=None
        self.landing_seen_at=None

    def update(self, controller, pose, *, team, bomb, now):
        point=(pose.x_norm,pose.y_norm)
        if self.active is not None:
            route,ground,points=self.routes[self.active]
            # A balcony drop need not land on the exact outbound polyline.
            # Accept only the recorded lower-floor exit, after the stairs,
            # outside the upper corridor and inside the base ground mask.
            box=route.get('landing_box')
            x,y=ground.pixel(point)
            landed=(box is not None and not self.retreating
                and self.stage==len(route.get('checkpoints',[]))
                and box[0]<=x<=box[2] and box[1]<=y<=box[3]
                and not ground.contains(point) and self.base.contains(point))
            stamp=getattr(pose,'observed_at',None)
            if landed and stamp is not None:
                if self.landing_seen_at is None:self.landing_seen_at=stamp
                elif stamp-self.landing_seen_at>=.1:
                    name=self.active
                    controller.switch_mission_ground(self.base)
                    self.active=None
                    return 'finished',name
            else:self.landing_seen_at=None
            if self.retreating:
                target=ground.norm(route['entry_path'][0])
            else:
                stops=route.get('checkpoints',[])+[len(points)-1]
                target=points[stops[self.stage]]
            if math.dist(ground.pixel(point),ground.pixel(target))<=route['arrival_px'] and ground.visible(point,target):
                if not self.retreating and self.stage<len(stops)-1:
                    begin=stops[self.stage];self.stage+=1;end=stops[self.stage]
                    controller.set_goal(NavGoal('wingman-ingress-'+self.active+'-'+str(self.stage),*points[end],.005),
                        continue_motion=True,prepared_path=(point,)+points[begin+1:end+1])
                    self.blocked_at=None
                    return 'active',self.active
                name=self.active
                controller.switch_mission_ground(self.base)
                self.active=None
                return ('aborted' if self.retreating else 'finished'),name
            failed=controller.reason in ('recovery_exhausted','no_verified_route','no_reachable_route_goal',
                'no_verified_recovery','recovery_timeout','no_progress_exhausted',
                'pose_outside_verified_ground')
            if failed:
                if self.blocked_at is None:self.blocked_at=now
                if now-self.blocked_at>=1. and not self.retreating:
                    # Only reverse the ground-level garage approach. Never infer
                    # that an upper-floor balcony/drop is traversable backwards.
                    x,y=ground.pixel(point)
                    if self.active=='apartments' and x<640 and y>750:
                        target=ground.norm(route['entry_path'][0]);path=ground.plan(point,target)
                        if path:
                            self.retreating=True
                            controller.switch_mission_ground(ground)
                            controller.set_goal(NavGoal('wingman-ingress-retreat',*target,.005),prepared_path=path)
                            return 'retreating',self.active
                    elif self.active!='apartments' and self.base.contains(point):
                        name=self.active;controller.switch_mission_ground(self.base);self.active=None
                        return 'aborted',name
            else:self.blocked_at=None
            return 'active',self.active
        if self.used or team!='T' or bomb not in ('carried_self','not_carried_self','carried_other'):return None,None
        x,y=controller.walkable.pixel(point);left,top,right,bottom=self.data['entry_box']
        if not left<=x<=right or not top<=y<=bottom:return None,None
        ordered=list(self.routes)
        self.rng.shuffle(ordered)
        ordered.sort(key=lambda name:(self.counts[name],name==self.previous))
        for name in ordered:
            route,ground,points=self.routes[name]
            if not ground.contains(point):continue
            entry=ground.plan(point,points[0])
            if not entry:continue
            self.stage=0
            end=(route.get('checkpoints',[])+[len(points)-1])[0]
            path=entry+points[1:end+1]
            self.base=controller._base_walkable
            self.active=name;self.used=True;self.previous=name;self.counts[name]+=1
            controller.switch_mission_ground(ground,actions=route['actions'])
            goal=NavGoal('wingman-ingress-'+name,*points[end],.005)
            controller.set_goal(goal,prepared_path=path)
            return 'started',name
        return None,None
