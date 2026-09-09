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


class WalkableMap:
    def __init__(self, mask: np.ndarray, *, clearance_px: float = 8., grid_step: int = 4):
        if mask.ndim != 2 or min(mask.shape) < 16:
            raise ValueError("Walkable mask must be a 2-D image at least 16x16")
        if not math.isfinite(clearance_px) or clearance_px < 1:
            raise ValueError("clearance_px must be finite and >= 1")
        self.height, self.width = mask.shape
        binary = np.uint8(mask >= 250)
        binary[[0, -1], :] = 0
        binary[:, [0, -1]] = 0
        self.free = cv2.distanceTransform(binary, cv2.DIST_L2, 5) > clearance_px
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
        mask = cv2.imread(str(folder / "walkable.png"), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise ValueError("Missing walkable.png")
        radar = cv2.imread(str(resolve_map_radar_path(map_id)), cv2.IMREAD_GRAYSCALE)
        if radar is None or radar.shape != mask.shape:
            raise ValueError("Walkable mask must have the same resolution as the map radar")
        return cls(mask, clearance_px=float(meta.get("clearance_px", 8.)))

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

    def plan(self, start, goal):
        s, g = self._attach(start), self._attach(goal)
        if s is None or g is None:
            return ()
        if self.visible(start, goal):
            return (tuple(start), tuple(goal))
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
                if not self.visible(self.norm((x * self.step, y * self.step)), self.norm((nx * self.step, ny * self.step))):
                    continue
                value = cost[current] + math.hypot(dx, dy)
                if value < cost.get(nxt, math.inf):
                    cost[nxt], parent[nxt] = value, current
                    heapq.heappush(queue, (value + math.hypot(nx - g[0], ny - g[1]), nxt))
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
            while j > i + 1 and not self.visible(points[i], points[j]):
                j -= 1
            simplified.append(points[j])
            i = j
        return tuple(simplified)
