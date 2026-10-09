"""Roam within one floor and occasionally approach an annotated walking portal."""
from types import SimpleNamespace
import math
from nav.roaming import RoamingGoals


class LayeredRoamingGoals(RoamingGoals):
    def __init__(self, ground, layer, portals, seed=None):
        super().__init__(ground,seed)
        self.layer = layer
        self.portals = portals
        self.last_portal_at = 0.

    def choose(self, point, now=0.):
        if now-self.last_portal_at >= 35.:
            options = []
            for portal in self.portals:
                pixels = portal['upper_to_lower']
                if self.layer == 'lower':
                    pixels = list(reversed(pixels))
                route = tuple(self.ground.norm(p) for p in pixels)
                approach = self.ground.plan(point,route[0])
                if approach and all(self.ground.visible(a,b) for a,b in zip(route,route[1:])):
                    path = tuple(approach)+route[1:]
                    length = sum(math.dist(self.ground.pixel(a),self.ground.pixel(b)) for a,b in zip(path,path[1:]))
                    options.append((length,portal['id'],path))
            if options:
                _,name,path = min(options)
                self.last_portal_at = now
                target = path[-1]
                return SimpleNamespace(id='portal_'+name,x=target[0],y=target[1],arrive_radius=.006),path
        return super().choose(point,now)
