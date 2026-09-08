"""Read player pose from the HUD minimap (center icon + arrow-tip yaw).

Product rule for CS2: the live HUD uses a *centered* radar. Absolute blob XY
away from the radar center is almost never the player — it is map chrome and
causes spin-in-place goal following. We only lock the center chevron.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from nav.calibration import NavCalibration
from nav.coords import normalize_angle_deg, pixel_to_norm
from nav.pose import PoseResult


def _label_components(mask: np.ndarray) -> list[tuple[int, int, float, float]]:
    """Return list of (area, label_id, cx, cy) for 4-connected components."""
    h, w = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components: list[tuple[int, int, float, float]] = []
    label = 1
    for y in range(h):
        for x in range(w):
            if not mask[y, x] or visited[y, x]:
                continue
            stack = [(y, x)]
            visited[y, x] = True
            pixels_y: list[int] = []
            pixels_x: list[int] = []
            while stack:
                cy, cx = stack.pop()
                pixels_y.append(cy)
                pixels_x.append(cx)
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))
            area = len(pixels_x)
            components.append(
                (area, label, float(np.mean(pixels_x)), float(np.mean(pixels_y)))
            )
            label += 1
    return components


def _component_mask(
    mask: np.ndarray,
    *,
    seed_x: float,
    seed_y: float,
) -> np.ndarray:
    """Flood-fill the connected component nearest to (seed_x, seed_y)."""
    h, w = mask.shape
    ys, xs = np.where(mask)
    out = np.zeros_like(mask, dtype=bool)
    if len(xs) == 0:
        return out
    d2 = (xs.astype(np.float64) - seed_x) ** 2 + (ys.astype(np.float64) - seed_y) ** 2
    i = int(np.argmin(d2))
    sx, sy = int(xs[i]), int(ys[i])
    stack = [(sy, sx)]
    out[sy, sx] = True
    while stack:
        cy, cx = stack.pop()
        for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
            if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not out[ny, nx]:
                out[ny, nx] = True
                stack.append((ny, nx))
    return out


def _yaw_from_arrow_tip(
    crop: np.ndarray,
    component: np.ndarray,
) -> float:
    """Heading from blob centroid toward arrow tip (same frame as bearing_deg)."""
    ys, xs = np.where(component)
    if len(xs) < 4:
        return 0.0

    xs_f = xs.astype(np.float64)
    ys_f = ys.astype(np.float64)
    cx = float(np.mean(xs_f))
    cy = float(np.mean(ys_f))
    dx = xs_f - cx
    dy = ys_f - cy
    dist2 = dx * dx + dy * dy
    if float(np.max(dist2)) < 1e-6:
        return 0.0

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


def _yaw_from_blob(
    crop: np.ndarray,
    mask: np.ndarray,
    *,
    local_cx: float,
    local_cy: float,
) -> float:
    component = _component_mask(mask, seed_x=local_cx, seed_y=local_cy)
    return _yaw_from_arrow_tip(crop, component)


class MinimapReader:
    def __init__(self, calibration: NavCalibration) -> None:
        self._cal = calibration
        self._mm = calibration.minimap
        self._last_ring_gray: Optional[np.ndarray] = None

    @property
    def calibration(self) -> NavCalibration:
        return self._cal

    @property
    def last_ring_gray(self) -> Optional[np.ndarray]:
        """Annular grayscale patch for RadarFlowSensor (player punched out)."""
        return self._last_ring_gray

    def _player_mask(self, crop: np.ndarray) -> np.ndarray:
        icon = self._mm.player_icon
        r = crop[:, :, 0].astype(np.int16)
        g = crop[:, :, 1].astype(np.int16)
        b = crop[:, :, 2].astype(np.int16)
        r0, g0, b0 = icon.rgb_min
        r1, g1, b1 = icon.rgb_max
        mask = (
            (r >= r0) & (r <= r1)
            & (g >= g0) & (g <= g1)
            & (b >= b0) & (b <= b1)
        )
        if self._mm.shape == "circle":
            h, w = mask.shape
            local_cx = self._mm.center_x - self._mm.rect.x
            local_cy = self._mm.center_y - self._mm.rect.y
            yy, xx = np.ogrid[:h, :w]
            dist = np.sqrt((xx - local_cx) ** 2 + (yy - local_cy) ** 2)
            mask &= dist <= float(self._mm.radius_px)
        return mask

    def _pick_center_blob(
        self,
        components: list[tuple[int, int, float, float]],
    ) -> Optional[tuple[int, float, float, float]]:
        """Pick player chevron: must sit near radar center (centered HUD)."""
        icon = self._mm.player_icon
        local_cx = self._mm.center_x - self._mm.rect.x
        local_cy = self._mm.center_y - self._mm.rect.y
        # Product: never lock map chrome. Prefer_center is hard max, not soft.
        max_dist = float(max(10.0, icon.prefer_center_px))
        best: Optional[tuple[float, int, float, float, float]] = None
        for area, _label, cx, cy in components:
            if area < icon.min_area_px or area > icon.max_area_px:
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

    def _build_ring_gray(self, crop: np.ndarray, component: np.ndarray) -> np.ndarray:
        """Grayscale radar ring with player icon removed — for motion sensing."""
        gray = (
            0.299 * crop[:, :, 0].astype(np.float32)
            + 0.587 * crop[:, :, 1].astype(np.float32)
            + 0.114 * crop[:, :, 2].astype(np.float32)
        )
        h, w = gray.shape
        local_cx = self._mm.center_x - self._mm.rect.x
        local_cy = self._mm.center_y - self._mm.rect.y
        yy, xx = np.ogrid[:h, :w]
        circ = (xx - local_cx) ** 2 + (yy - local_cy) ** 2 <= float(self._mm.radius_px) ** 2
        hole_r = max(18.0, float(self._mm.player_icon.prefer_center_px) + 6.0)
        hole = (xx - local_cx) ** 2 + (yy - local_cy) ** 2 <= hole_r ** 2
        ring = gray.copy()
        ring[~(circ & ~hole)] = 0.0
        ring[component] = 0.0
        return ring

    def read(self, frame: np.ndarray) -> PoseResult:
        self._last_ring_gray = None
        if frame is None or frame.size == 0:
            return PoseResult.invalid()

        rect = self._mm.rect
        h_frame, w_frame = frame.shape[:2]
        x1 = max(0, min(rect.x, w_frame - 1))
        y1 = max(0, min(rect.y, h_frame - 1))
        x2 = max(x1 + 1, min(rect.x + rect.w, w_frame))
        y2 = max(y1 + 1, min(rect.y + rect.h, h_frame))
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return PoseResult.invalid()

        mask = self._player_mask(crop)
        components = _label_components(mask)
        picked = self._pick_center_blob(components)
        if picked is None:
            return PoseResult.invalid()

        area, local_cx, local_cy, center_dist = picked
        component = _component_mask(mask, seed_x=local_cx, seed_y=local_cy)
        yaw_deg = _yaw_from_arrow_tip(crop, component)
        self._last_ring_gray = self._build_ring_gray(crop, component)

        icon = self._mm.player_icon
        # Centered radar: report icon at radar center (world XY is unknown here).
        center_x_norm = (self._mm.center_x - rect.x) / max(rect.w, 1)
        center_y_norm = (self._mm.center_y - rect.y) / max(rect.h, 1)
        center_bonus = max(0.0, 1.0 - center_dist / max(icon.prefer_center_px, 1.0))
        area_score = min(1.0, area / float(icon.max_area_px))
        confidence = max(0.0, min(1.0, 0.35 * area_score + 0.65 * center_bonus))

        return PoseResult(
            x_norm=float(center_x_norm),
            y_norm=float(center_y_norm),
            yaw_deg=yaw_deg,
            confidence=confidence,
            valid=confidence >= self._cal.pose.min_confidence,
            blob_area_px=area,
            radar_mode="centered",
        )
