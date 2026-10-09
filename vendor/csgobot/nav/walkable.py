"""Conservative route planning on an explicitly annotated walkable mask.

White = verified same-floor walkable ground. Black = blocked or unknown.
The character radius is removed from free space before planning. No direct
fallback, diagonal corner cutting, or attachment through an unverified wall.
"""
from __future__ import annotations

import heapq
import math
import json
import hashlib
from pathlib import Path

import cv2
import numpy as np

from nav.paths import resolve_visual_profile_file, resolve_map_radar_path


def read_grayscale(path: Path) -> np.ndarray:
    """Decode our own bytes: detector libraries may replace cv2.imread and
    return HxWx1 for grayscale. Path.read_bytes also supports Windows Unicode.
    """
    path = Path(path)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Cannot read navigation image: {path}") from exc
    if not payload:
        raise ValueError(f"Empty navigation image: {path}")
    try:
        image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    except cv2.error as exc:
        raise ValueError(f"Cannot decode navigation image: {path}") from exc
    if image is None or image.ndim != 2:
        raise ValueError(f"Invalid grayscale navigation image: {path}")
    return image


class WalkableMap:
    def __init__(self, mask: np.ndarray, *, clearance_px: float = 8., grid_step: int = 4, search_weight: float = 1.):
        if mask.ndim != 2 or min(mask.shape) < 16:
            raise ValueError("Walkable mask must be a 2-D image at least 16x16")
        if not math.isfinite(clearance_px) or clearance_px < 1:
            raise ValueError("clearance_px must be finite and >= 1")
        if not math.isfinite(search_weight) or not 1. <= search_weight <= 2.:
            raise ValueError("search_weight must be finite and between 1 and 2")
        self.search_weight = float(search_weight)
        self.height, self.width = mask.shape
        self.footprint = clearance_px
        binary = np.uint8(mask >= 250)
        binary[[0, -1], :] = 0
        binary[:, [0, -1]] = 0
        self.clearance = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
        self.free = self.clearance > clearance_px
        self._edge_cache = {}
        self.step = max(1, min(8, int(grid_step)))
        self.grid = self.free[::self.step, ::self.step]

    @classmethod
    def load(cls, map_id: str, profile_dir: Path | None = None):
        meta_path = (profile_dir / "navigation.json") if profile_dir is not None else resolve_visual_profile_file(map_id, "navigation.json")
        folder = meta_path.parent
        if not meta_path.is_file():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("map_id") != map_id:
            raise ValueError("Navigation profile map_id mismatch")
        expected_hash = meta.get("map_sha256")
        if expected_hash and hashlib.sha256(resolve_map_radar_path(map_id).read_bytes()).hexdigest() != expected_hash:
            raise ValueError("Map changed since walkable profile was built")
        mask = read_grayscale(folder / "walkable.png")
        if mask is None:
            raise ValueError("Missing walkable.png")
        radar = read_grayscale(resolve_map_radar_path(map_id))
        if radar is None or radar.shape != mask.shape:
            raise ValueError("Walkable mask must have the same resolution as the map radar")
        return cls(mask, clearance_px=float(meta.get("clearance_px", 8.)),
                   grid_step=int(meta.get("grid_step", 4)),
                   search_weight=float(meta.get("search_weight", 1.)))

    def pixel(self, point):
        return (float(point[0]) * (self.width - 1), float(point[1]) * (self.height - 1))

    def norm(self, point):
        return (float(point[0]) / (self.width - 1), float(point[1]) / (self.height - 1))

    def contains(self, point):
        x, y = self.pixel(point)
        return (math.isfinite(x) and math.isfinite(y) and 0 <= x <= self.width - 1
                and 0 <= y <= self.height - 1 and bool(self.free[int(round(y)), int(round(x))]))

    def visible(self, start, end):
        a, b = np.array(self.pixel(start)), np.array(self.pixel(end))
        if not np.isfinite(a).all() or not np.isfinite(b).all():
            return False
        # Half-pixel sampling also catches thin diagonals between grid nodes.
        count = max(2, int(np.linalg.norm(b - a) * 2) + 1)
        xy = np.rint(np.linspace(a, b, count)).astype(int)
        if ((xy[:, 0] < 0) | (xy[:, 0] >= self.width) | (xy[:, 1] < 0) | (xy[:, 1] >= self.height)).any():
            return False
        return bool(self.free[xy[:, 1], xy[:, 0]].all())

    def comfortable_visible(self, start, end):
        if not self.visible(start,end):
            return False
        minimum = min(self.clearance_at(start),self.clearance_at(end),self.footprint+5.)-.1
        a,b = np.array(self.pixel(start)),np.array(self.pixel(end))
        xy = np.rint(np.linspace(a,b,max(2,int(np.linalg.norm(b-a)*2)+1))).astype(int)
        return bool((self.clearance[xy[:,1],xy[:,0]] >= minimum).all())

    def _attach(self, point):
        if not self.contains(point):
            return None
        px, py = self.pixel(point)
        gx, gy = round(px / self.step), round(py / self.step)
        candidates = []
        for y in range(max(0, gy - 2), min(self.grid.shape[0], gy + 3)):
            for x in range(max(0, gx - 2), min(self.grid.shape[1], gx + 3)):
                p = self.norm((x * self.step, y * self.step))
                if self.grid[y, x] and self.visible(point, p):
                    candidates.append(((x * self.step - px)**2 + (y * self.step - py)**2, (x, y)))
        return min(candidates)[1] if candidates else None

    def clearance_at(self, point):
        x,y = self.pixel(point)
        if not (math.isfinite(x) and math.isfinite(y) and 0<=x<=self.width-1 and 0<=y<=self.height-1):
            return 0.
        return float(self.clearance[round(y),round(x)])

    def increasing_clearance(self, start, end):
        a,b = np.array(self.pixel(start)), np.array(self.pixel(end))
        if not np.isfinite(a).all() or not np.isfinite(b).all():
            return False
        xy = np.rint(np.linspace(a,b,max(2,int(np.linalg.norm(b-a)*2)+1))).astype(int)
        if ((xy[:,0]<0)|(xy[:,0]>=self.width)|(xy[:,1]<0)|(xy[:,1]>=self.height)).any():
            return False
        values = self.clearance[xy[:,1],xy[:,0]]
        return bool(values[0]>0 and values[-1]>values[0]+.2 and
                    np.all(np.diff(values)>=-.25))

    def boundary_exit(self, point, radius=12, *, prefer_interior=False):
        if self.contains(point) or self.clearance_at(point)<=0:
            return None
        x,y = map(round,self.pixel(point))
        options=[]
        for ny in range(max(0,y-radius),min(self.height,y+radius+1)):
            for nx in range(max(0,x-radius),min(self.width,x+radius+1)):
                distance=math.hypot(nx-x,ny-y)
                if distance<=radius and self.free[ny,nx]:
                    cost=distance
                    if prefer_interior:
                        cost+=4.*max(0.,self.footprint+4.-self.clearance[ny,nx])
                    options.append((cost,-self.clearance[ny,nx],self.norm((nx,ny))))
        for _,_,target in sorted(options):
            if self.increasing_clearance(point,target):
                return target
        return None

    def excluding(self, obstacles):
        """Session-local restrictions can only remove existing free space."""
        result = object.__new__(WalkableMap)
        result.width, result.height, result.step = self.width, self.height, self.step
        result.clearance = self.clearance
        result.footprint = self.footprint
        result.search_weight = self.search_weight
        binary = np.uint8(self.free)
        for center, radius in obstacles:
            x, y = self.pixel(center)
            cv2.circle(binary, (round(x), round(y)), int(radius), 0, -1)
        result.free = binary.astype(bool)
        result.grid = result.free[::self.step, ::self.step]
        result._edge_cache = {}
        return result

    def _edge_clear(self, a, b):
        # Build each adjacent-edge direction in one vectorized pass. Scalar
        # half-pixel visibility for thousands of A* edges stalls live control.
        direction = (b[0]-a[0], b[1]-a[1])
        if direction not in self._edge_cache:
            dx,dy = direction
            yy,xx = np.indices(self.grid.shape)
            gx,gy = xx*self.step,yy*self.step
            count = max(2,int(math.hypot(dx,dy)*self.step*2)+1)
            clear = np.ones(self.grid.shape,bool)
            for t in np.linspace(0.,1.,count):
                x = np.rint(gx+t*dx*self.step).astype(int)
                y = np.rint(gy+t*dy*self.step).astype(int)
                inside = (x>=0)&(x<self.width)&(y>=0)&(y<self.height)
                clear &= inside & self.free[np.clip(y,0,self.height-1),np.clip(x,0,self.width-1)]
            self._edge_cache[direction] = clear
        return bool(self._edge_cache[direction][a[1],a[0]])

    def plan(self, start, goal):
        s, g = self._attach(start), self._attach(goal)
        if s is None or g is None:
            return ()
        if self.comfortable_visible(start, goal):
            return (tuple(start), tuple(goal))
        if self.search_weight > 1.:
            chain = self._bidirectional_chain(s,g)
            if not chain:
                return ()
        else:
            queue = [(0., s)]
            cost, parent = {s: 0.}, {}
            closed = set()
            while queue:
                _, current = heapq.heappop(queue)
                if current in closed:
                    continue
                if current == g:
                    break
                closed.add(current)
                x, y = current
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    nxt = (x + dx, y + dy)
                    nx, ny = nxt
                    if not (0 <= ny < self.grid.shape[0] and 0 <= nx < self.grid.shape[1] and self.grid[ny, nx]):
                        continue
                    if dx and dy and not (self.grid[y, nx] and self.grid[ny, x]):
                        continue
                    if not self._edge_clear(current, nxt):
                        continue
                    # Prefer the middle of a corridor over grazing its inflated edge.
                    clearance = float(self.clearance[ny*self.step,nx*self.step])
                    penalty = 2.*max(0.,(self.footprint+10.-clearance)/10.)
                    value = cost[current] + math.hypot(dx, dy)*(1.+penalty)
                    if value < cost.get(nxt, math.inf):
                        cost[nxt], parent[nxt] = value, current
                        heapq.heappush(queue, (value + self.search_weight * math.hypot(nx - g[0], ny - g[1]), nxt))
            if g not in cost:
                return ()
            chain = [g]
            while chain[-1] != s:
                chain.append(parent[chain[-1]])
        points = [tuple(start)] + [self.norm((x * self.step, y * self.step)) for x, y in reversed(chain)] + [tuple(goal)]
        simplified = [points[0]]
        i = 0
        while i < len(points) - 1:
            j = len(points) - 1
            while j > i + 1 and not self.comfortable_visible(points[i], points[j]):
                j -= 1
            simplified.append(points[j])
            i = j
        return tuple(simplified)


    def _bidirectional_chain(self,start,goal):
        """Find a feasible route from both ends; all original edge checks apply.

        A weighted search trades shortest-path optimality for lower decision
        latency. Reverse costs use the forward edge's destination clearance.
        """
        queues=[[(0.,start)],[(0.,goal)]]
        costs=[{start:0.},{goal:0.}];parents=[{},{}];closed=[set(),set()]
        meeting=None;side=0
        while queues[0] and queues[1]:
            queue=queues[side];_,current=heapq.heappop(queue)
            if current in closed[side]:continue
            if current in costs[1-side]:meeting=current;break
            closed[side].add(current);x,y=current
            target=goal if side==0 else start
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                nx,ny=x+dx,y+dy;nxt=(nx,ny)
                if not (0<=ny<self.grid.shape[0] and 0<=nx<self.grid.shape[1] and self.grid[ny,nx]):continue
                if dx and dy and not (self.grid[y,nx] and self.grid[ny,x]):continue
                if not (self._edge_clear(current,nxt) if side==0 else self._edge_clear(nxt,current)):continue
                px,py=nxt if side==0 else current
                clearance=float(self.clearance[py*self.step,px*self.step])
                penalty=2.*max(0.,(self.footprint+10.-clearance)/10.)
                value=costs[side][current]+math.hypot(dx,dy)*(1.+penalty)
                if value<costs[side].get(nxt,math.inf):
                    costs[side][nxt]=value;parents[side][nxt]=current
                    heapq.heappush(queue,(value+self.search_weight*math.dist(nxt,target),nxt))
            side=1-side
        if meeting is None:return ()
        left=[meeting]
        while left[-1]!=start:left.append(parents[0][left[-1]])
        path=list(reversed(left));current=meeting
        while current!=goal:
            current=parents[1][current];path.append(current)
        return list(reversed(path))
