"""Read player pose from the HUD minimap (color blob + PCA yaw)."""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from nav.calibration import MinimapCalibration, NavCalibration
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


def _yaw_from_blob(
    crop: np.ndarray,
    mask: np.ndarray,
    *,
    local_cx: float,
    local_cy: float,
) -> float:
    ys, xs = np.where(mask)
    if len(xs) < 4:
        return 0.0
    xs_f = xs.astype(np.float64) - local_cx
    ys_f = ys.astype(np.float64) - local_cy
    cov_xx = float(np.mean(xs_f * xs_f))
    cov_yy = float(np.mean(ys_f * ys_f))
    cov_xy = float(np.mean(xs_f * ys_f))
    if cov_xx + cov_yy < 1e-6:
        return 0.0
    angle_rad = 0.5 * math.atan2(2.0 * cov_xy, cov_xx - cov_yy)
    yaw = math.degrees(angle_rad)
    return normalize_angle_deg(yaw)


class MinimapReader:
    def __init__(self, calibration: NavCalibration) -> None:
        self._cal = calibration
        self._mm = calibration.minimap

    @property
    def calibration(self) -> NavCalibration:
        return self._cal

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

    def _pick_blob(
        self,
        components: list[tuple[int, int, float, float]],
    ) -> Optional[tuple[int, float, float]]:
        icon = self._mm.player_icon
        local_cx = self._mm.center_x - self._mm.rect.x
        local_cy = self._mm.center_y - self._mm.rect.y
        best: Optional[tuple[float, int, float, float]] = None
        for area, _label, cx, cy in components:
            if area < icon.min_area_px or area > icon.max_area_px:
                continue
            dist = math.hypot(cx - local_cx, cy - local_cy)
            if dist > icon.prefer_center_px * 4.0:
                continue
            score = dist - area * 0.02
            if best is None or score < best[0]:
                best = (score, area, cx, cy)
        if best is None:
            return None
        _score, area, cx, cy = best
        return area, cx, cy

    def read(self, frame: np.ndarray) -> PoseResult:
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
        picked = self._pick_blob(components)
        if picked is None:
            return PoseResult.invalid()

        area, local_cx, local_cy = picked
        frame_px = rect.x + local_cx
        frame_py = rect.y + local_cy
        x_norm, y_norm = pixel_to_norm(
            frame_px,
            frame_py,
            rect_x=rect.x,
            rect_y=rect.y,
            rect_w=rect.w,
            rect_h=rect.h,
        )
        yaw_deg = _yaw_from_blob(crop, mask, local_cx=local_cx, local_cy=local_cy)

        icon = self._mm.player_icon
        center_dist = math.hypot(
            local_cx - (self._mm.center_x - rect.x),
            local_cy - (self._mm.center_y - rect.y),
        )
        center_bonus = max(0.0, 1.0 - center_dist / max(icon.prefer_center_px, 1.0))
        area_score = min(1.0, area / float(icon.max_area_px))
        confidence = max(0.0, min(1.0, 0.45 * area_score + 0.55 * center_bonus))

        return PoseResult(
            x_norm=x_norm,
            y_norm=y_norm,
            yaw_deg=yaw_deg,
            confidence=confidence,
            valid=confidence >= self._cal.pose.min_confidence,
            blob_area_px=area,
        )
