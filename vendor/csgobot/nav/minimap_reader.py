"""Read player icon from the HUD minimap (center lock) + expose radar ring.

CS2 centered radar: player icon stays near the *radar disk center* (not crop
chrome at 0.68). Farm HUDs vary in size — prefer live Hough circle, fall back
to calibration rect.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from nav.calibration import NavCalibration
from nav.coords import normalize_angle_deg
from nav.pose import PoseResult
from nav.radar_geom import RadarCircle, detect_radar_circle

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore


def _label_components(mask: np.ndarray) -> list[tuple[int, float, float]]:
    if cv2 is not None:
        num, _labels, stats, cents = cv2.connectedComponentsWithStats(
            mask.astype(np.uint8), connectivity=8
        )
        out: list[tuple[int, float, float]] = []
        for i in range(1, num):
            area = int(stats[i, cv2.CC_STAT_AREA])
            out.append((area, float(cents[i][0]), float(cents[i][1])))
        return out
    # Fallback flood (rare)
    h, w = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components: list[tuple[int, float, float]] = []
    for y in range(h):
        for x in range(w):
            if not mask[y, x] or visited[y, x]:
                continue
            stack = [(y, x)]
            visited[y, x] = True
            xs: list[int] = []
            ys: list[int] = []
            while stack:
                cy, cx = stack.pop()
                ys.append(cy)
                xs.append(cx)
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))
            components.append((len(xs), float(np.mean(xs)), float(np.mean(ys))))
    return components


def _yaw_from_arrow_tip(crop: np.ndarray, component: np.ndarray) -> float:
    ys, xs = np.where(component)
    if len(xs) < 4:
        return -90.0
    xs_f = xs.astype(np.float64)
    ys_f = ys.astype(np.float64)
    cx = float(np.mean(xs_f))
    cy = float(np.mean(ys_f))
    dx = xs_f - cx
    dy = ys_f - cy
    dist2 = dx * dx + dy * dy
    if float(np.max(dist2)) < 1e-6:
        return -90.0
    order = np.argsort(dist2)
    tail_n = max(3, len(order) // 5)
    candidates = order[-tail_n:]
    samples = crop[ys[candidates], xs[candidates]].astype(np.float64)
    brightness = samples.mean(axis=1) if samples.ndim == 2 else samples
    score = dist2[candidates] + 0.15 * brightness
    best = int(candidates[int(np.argmax(score))])
    tip_dx = float(xs_f[best] - cx)
    tip_dy = float(ys_f[best] - cy)
    return normalize_angle_deg(math.degrees(math.atan2(tip_dy, tip_dx)))


class MinimapReader:
    def __init__(self, calibration: NavCalibration) -> None:
        self._cal = calibration
        self._mm = calibration.minimap
        self._last_ring_gray: Optional[np.ndarray] = None
        self._last_circle: Optional[RadarCircle] = None

    @property
    def calibration(self) -> NavCalibration:
        return self._cal

    @property
    def last_ring_gray(self) -> Optional[np.ndarray]:
        return self._last_ring_gray

    @property
    def last_circle(self) -> Optional[RadarCircle]:
        return self._last_circle

    def _player_mask(self, crop: np.ndarray) -> np.ndarray:
        """T = yellow/gold chevron; CT = cyan (legacy calib)."""
        r = crop[:, :, 0].astype(np.int16)
        g = crop[:, :, 1].astype(np.int16)
        b = crop[:, :, 2].astype(np.int16)
        icon = self._mm.player_icon
        r0, g0, b0 = icon.rgb_min
        r1, g1, b1 = icon.rgb_max
        cyan = (
            (r >= r0) & (r <= r1)
            & (g >= g0) & (g <= g1)
            & (b >= b0) & (b <= b1)
        )
        # T-side chevron: saturated yellow/gold (avoid sand-colored map fill).
        yellow = (
            (r > 185) & (g > 165) & (b < 110)
            & ((r - b) > 70) & ((g - b) > 55)
        )
        return cyan | yellow

    def _pick_center_blob(
        self,
        components: list[tuple[int, float, float]],
        *,
        local_cx: float,
        local_cy: float,
        max_dist: float,
    ) -> Optional[tuple[int, float, float, float]]:
        icon = self._mm.player_icon
        best: Optional[tuple[float, int, float, float, float]] = None
        for area, cx, cy in components:
            if area < icon.min_area_px or area > max(icon.max_area_px, 140):
                continue
            dist = math.hypot(cx - local_cx, cy - local_cy)
            if dist > max_dist:
                continue
            score = dist - area * 0.02
            if best is None or score < best[0]:
                best = (score, area, cx, cy, dist)
        if best is None:
            return None
        _score, area, cx, cy, dist = best
        return area, cx, cy, dist

    def _build_ring_gray(
        self,
        crop: np.ndarray,
        component: np.ndarray,
        *,
        local_cx: float,
        local_cy: float,
        radius: float,
    ) -> np.ndarray:
        gray = (
            0.299 * crop[:, :, 0].astype(np.float32)
            + 0.587 * crop[:, :, 1].astype(np.float32)
            + 0.114 * crop[:, :, 2].astype(np.float32)
        )
        h, w = gray.shape
        yy, xx = np.ogrid[:h, :w]
        circ = (xx - local_cx) ** 2 + (yy - local_cy) ** 2 <= radius ** 2
        hole_r = max(18.0, float(self._mm.player_icon.prefer_center_px) + 6.0)
        hole = (xx - local_cx) ** 2 + (yy - local_cy) ** 2 <= hole_r ** 2
        ring = gray.copy()
        ring[~(circ & ~hole)] = 0.0
        ring[component] = 0.0
        return ring

    def _crop_from_circle(
        self, frame: np.ndarray, circle: RadarCircle
    ) -> tuple[np.ndarray, float, float, float]:
        x, y, s, _ = circle.rect
        h, w = frame.shape[:2]
        x2 = min(w, x + s)
        y2 = min(h, y + s)
        crop = frame[y:y2, x:x2]
        if crop.size == 0:
            return crop, 0.0, 0.0, 0.0
        if cv2 is not None and (crop.shape[0] != s or crop.shape[1] != s):
            crop = cv2.resize(crop, (max(s, 32), max(s, 32)))
        # Circle center in crop coords
        local_cx = circle.cx - x
        local_cy = circle.cy - y
        # After resize, scale locals
        if crop.shape[0] != (y2 - y) or crop.shape[1] != (x2 - x):
            sy = crop.shape[0] / max(y2 - y, 1)
            sx = crop.shape[1] / max(x2 - x, 1)
            local_cx *= sx
            local_cy *= sy
        radius = float(circle.radius) * (crop.shape[0] / max(2 * circle.radius + 8, 1))
        return crop, local_cx, local_cy, radius

    def _crop_from_calib(
        self, frame: np.ndarray
    ) -> tuple[np.ndarray, float, float, float]:
        rect = self._mm.rect
        h_frame, w_frame = frame.shape[:2]
        x1 = max(0, min(rect.x, w_frame - 1))
        y1 = max(0, min(rect.y, h_frame - 1))
        x2 = max(x1 + 1, min(rect.x + rect.w, w_frame))
        y2 = max(y1 + 1, min(rect.y + rect.h, h_frame))
        crop = frame[y1:y2, x1:x2]
        local_cx = float(self._mm.center_x - rect.x)
        local_cy = float(self._mm.center_y - rect.y)
        radius = float(self._mm.radius_px)
        return crop, local_cx, local_cy, radius

    def read(self, frame: np.ndarray) -> PoseResult:
        self._last_ring_gray = None
        self._last_circle = None
        if frame is None or frame.size == 0:
            return PoseResult.invalid()

        circle = detect_radar_circle(frame)
        self._last_circle = circle
        if circle is not None:
            crop, local_cx, local_cy, radius = self._crop_from_circle(frame, circle)
            max_dist = max(22.0, radius * 0.22)
        else:
            crop, local_cx, local_cy, radius = self._crop_from_calib(frame)
            max_dist = float(max(12.0, self._mm.player_icon.prefer_center_px))

        if crop.size == 0:
            return PoseResult.invalid()

        mask = self._player_mask(crop)
        # Keep only inside radar disk
        h, w = mask.shape
        yy, xx = np.ogrid[:h, :w]
        mask &= (xx - local_cx) ** 2 + (yy - local_cy) ** 2 <= radius ** 2

        components = _label_components(mask)
        picked = self._pick_center_blob(
            components, local_cx=local_cx, local_cy=local_cy, max_dist=max_dist
        )
        if picked is None:
            return PoseResult.invalid()

        area, bx, by, center_dist = picked
        # Component mask for yaw
        if cv2 is not None:
            num, labels, _stats, _c = cv2.connectedComponentsWithStats(
                mask.astype(np.uint8), connectivity=8
            )
            # pick label nearest seed
            best_label = 0
            best_d = 1e9
            for i in range(1, num):
                ys, xs = np.where(labels == i)
                if len(xs) == 0:
                    continue
                d = (float(np.mean(xs)) - bx) ** 2 + (float(np.mean(ys)) - by) ** 2
                if d < best_d:
                    best_d = d
                    best_label = i
            component = labels == best_label
        else:
            component = mask

        yaw_deg = _yaw_from_arrow_tip(crop, component)
        self._last_ring_gray = self._build_ring_gray(
            crop, component, local_cx=local_cx, local_cy=local_cy, radius=radius
        )

        # Centered radar: report icon at radar center (world XY from PlaceLocalizer).
        center_bonus = max(0.0, 1.0 - center_dist / max(max_dist, 1.0))
        area_score = min(1.0, area / 120.0)
        confidence = max(0.0, min(1.0, 0.35 * area_score + 0.65 * center_bonus))

        return PoseResult(
            x_norm=0.5,
            y_norm=0.5,
            yaw_deg=yaw_deg,
            confidence=confidence,
            valid=confidence >= self._cal.pose.min_confidence,
            blob_area_px=area,
            radar_mode="centered",
        )
