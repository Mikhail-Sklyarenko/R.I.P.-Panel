"""Measured HUD-to-map registration. Route goals never enter perception.

The reference radar is always available; optional calibrated HUD atlas images
reduce the rendering gap. Every result is an independently verified similarity
transform, not a place-name coordinate or integrated mouse command.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from nav.coords import normalize_angle_deg
from nav.paths import resolve_map_radar_path, resolve_visual_profile_file
from nav.pose import PoseResult


@dataclass(frozen=True)
class Registration:
    matrix: np.ndarray
    confidence: float
    inliers: int
    residual_px: float
    source: str


def gray_features(rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY) if rgb.ndim == 3 else rgb
    return cv2.createCLAHE(2.0, (8, 8)).apply(gray.astype(np.uint8))


class VisualLocalizer:
    def __init__(self, map_id: str, *, map_rgb=None, profile_dir: Path | None = None):
        self.map_id = map_id
        manifest = (profile_dir / "atlas.json") if profile_dir is not None else resolve_visual_profile_file(map_id, "atlas.json")
        self.profile_dir = manifest.parent
        if map_rgb is None:
            bgr = cv2.imread(str(resolve_map_radar_path(map_id)))
            if bgr is None:
                raise ValueError(f"Cannot read radar for {map_id}")
            map_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        self.height, self.width = map_rgb.shape[:2]
        self.map_rgb = map_rgb
        self.sift = cv2.SIFT_create(nfeatures=2500, contrastThreshold=0.015)
        self.matcher = cv2.BFMatcher(cv2.NORM_L2)
        self.references = []
        self.reason = "not_observed"
        self.last_registration = None
        self._previous = None
        self._pending = None
        self._confirmed = False
        self._pyramid = None
        self.add_reference(map_rgb, np.array([[1., 0., 0.], [0., 1., 0.]]), "radar")
        if manifest.is_file():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data.get("map_id") != map_id:
                raise ValueError("Atlas map_id mismatch")
            for item in data.get("references", []):
                path = (self.profile_dir / item["image"]).resolve()
                if not path.is_relative_to(self.profile_dir.resolve()):
                    raise ValueError("Atlas image must be inside profile directory")
                bgr = cv2.imread(str(path))
                if bgr is None:
                    raise ValueError(f"Missing atlas image: {path.name}")
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                self.add_reference(rgb, np.asarray(item["to_map"], dtype=float), path.name)

    def add_reference(self, rgb, to_map, name):
        if to_map.shape != (2, 3) or not np.isfinite(to_map).all():
            raise ValueError("Atlas transform must be a finite 2x3 matrix")
        # Crop borders and color annotations do not constitute map features.
        mask = np.uint8(np.any(rgb > 8, axis=2)) * 255
        mask = cv2.erode(mask, np.ones((5, 5), np.uint8))
        kp, desc = self.sift.detectAndCompute(gray_features(rgb), mask)
        if desc is not None:
            xy = np.float32([k.pt for k in kp])
            mapped = xy @ to_map[:, :2].T + to_map[:, 2]
            self.references.append((name, mapped, desc))

    def reset(self):
        self._previous = self._pending = None
        self._confirmed = False
        self.last_registration = None

    def _edge_agreement(self, rgb, mask, matrix):
        """Validate a proposed transform using wall pixels not descriptor votes.

        A low descriptor inlier ratio is common across render styles. It is
        never accepted on that basis alone: contours must agree in both
        directions and be spread over the radar.
        """
        projected = cv2.warpAffine(
            self.map_rgb, matrix, (rgb.shape[1], rgb.shape[0]),
            flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        )
        expected = cv2.Canny(projected, 25, 80)
        observed = cv2.Canny(rgb, 25, 80)
        interior = cv2.erode(mask, np.ones((5, 5), np.uint8)) > 0
        a, b = (observed > 0) & interior, (expected > 0) & interior
        if a.sum() < 120 or b.sum() < 120:
            return None
        dt_expected = cv2.distanceTransform(255 - expected, cv2.DIST_L2, 3)
        dt_observed = cv2.distanceTransform(255 - observed, cv2.DIST_L2, 3)
        recall = float(np.mean(dt_expected[a] < 2.))
        precision = float(np.mean(dt_observed[b] < 2.))
        # Require agreement in at least three quadrants, not one matching room.
        support = a & (dt_expected < 2.)
        h, w = a.shape
        regions = [(slice(0, h//2), slice(0, w//2)),
                   (slice(0, h//2), slice(w//2, w)),
                   (slice(h//2, h), slice(0, w//2)),
                   (slice(h//2, h), slice(w//2, w))]
        covered = sum(np.count_nonzero(support[region]) >= 25 for region in regions)
        if recall < .78 or precision < .50 or covered < 3:
            return None
        return min(1., .55 * recall + .45 * precision)

    def _map_candidates(self, rgb, mask):
        if self._pyramid is None:
            # Match at the scale of live HUD details before geometric fitting.
            # All target coordinates are still in the original map pixels.
            self._pyramid = []
            for scale in (.25, .35, .5):
                resized = cv2.resize(self.map_rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                for kind in ("gray", "edge"):
                    gray = gray_features(resized) if kind == "gray" else cv2.GaussianBlur(cv2.Canny(resized, 25, 80), (3, 3), 0)
                    kp, desc = self.sift.detectAndCompute(gray, None)
                    if desc is not None:
                        self._pyramid.append((kind, np.float32([k.pt for k in kp]) / scale, desc))
        candidates = []
        for kind in ("gray", "edge"):
            gray = gray_features(rgb) if kind == "gray" else cv2.GaussianBlur(cv2.Canny(rgb, 25, 80), (3, 3), 0)
            kp, desc = self.sift.detectAndCompute(gray, mask)
            if desc is None:
                continue
            points = np.float32([k.pt for k in kp])
            for ref_kind, target_xy, target_desc in self._pyramid:
                if ref_kind != kind:
                    continue
                pairs = self.matcher.knnMatch(desc, target_desc, k=2)
                unique = {}
                for pair in pairs:
                    if len(pair) == 2 and pair[0].distance < .8 * pair[1].distance:
                        m = pair[0]
                        if m.trainIdx not in unique or m.distance < unique[m.trainIdx].distance:
                            unique[m.trainIdx] = m
                matches = list(unique.values())
                if len(matches) < 6:
                    continue
                src = points[[m.queryIdx for m in matches]]
                dst = target_xy[[m.trainIdx for m in matches]]
                matrix, flags = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=6., maxIters=3500, confidence=.995)
                if matrix is None or flags is None or not np.isfinite(matrix).all():
                    continue
                good = flags.ravel().astype(bool)
                scale = float(np.linalg.norm(matrix[:, 0]))
                if good.sum() < 6 or not .5 <= scale <= 8.:
                    continue
                if cv2.contourArea(cv2.convexHull(src[good])) < np.count_nonzero(mask) * .08:
                    continue
                agreement = self._edge_agreement(rgb, mask, matrix)
                if agreement is None:
                    continue
                residual = float(np.median(np.linalg.norm(src[good] @ matrix[:, :2].T + matrix[:, 2] - dst[good], axis=1)))
                candidates.append(Registration(matrix, agreement, int(good.sum()), residual, "map_contours"))
        return candidates

    def register(self, rgb, mask) -> Registration | None:
        self.last_registration = None
        if rgb.size == 0 or not np.any(mask):
            self.reason = "empty_radar"
            return None
        kp, desc = self.sift.detectAndCompute(gray_features(rgb), mask)
        if desc is None or len(kp) < 10:
            self.reason = "too_few_features"
            return None
        xy = np.float32([k.pt for k in kp])
        candidates = []
        for name, reference_xy, reference_desc in self.references:
            pairs = self.matcher.knnMatch(desc, reference_desc, k=2)
            matches = [p[0] for p in pairs if len(p) == 2 and p[0].distance < .70 * p[1].distance]
            # One reference feature may only support one correspondence.
            unique = {}
            for match in matches:
                old = unique.get(match.trainIdx)
                if old is None or match.distance < old.distance:
                    unique[match.trainIdx] = match
            matches = list(unique.values())
            if len(matches) < 10:
                continue
            src = xy[[m.queryIdx for m in matches]]
            dst = np.float32(reference_xy[[m.trainIdx for m in matches]])
            matrix, inlier_mask = cv2.estimateAffinePartial2D(
                src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.,
                maxIters=2500, confidence=.995,
            )
            if matrix is None or inlier_mask is None or not np.isfinite(matrix).all():
                continue
            good = inlier_mask.ravel().astype(bool)
            n = int(good.sum())
            scale = float(np.linalg.norm(matrix[:, 0]))
            if n < 10 or n / len(matches) < .6 or not .2 <= scale <= 15:
                continue
            # Features must cover a 2-D patch, not one icon or a straight edge.
            hull_area = cv2.contourArea(cv2.convexHull(src[good]))
            if hull_area < np.count_nonzero(mask) * .08:
                continue
            residual = np.linalg.norm(src[good] @ matrix[:, :2].T + matrix[:, 2] - dst[good], axis=1)
            error = float(np.median(residual))
            if error > 2.0:
                continue
            confidence = min(1., n / 24.) * (n / len(matches)) * max(.5, 1. - error / 6.)
            candidates.append(Registration(matrix, confidence, n, error, name))
        if not candidates or max(c.confidence for c in candidates) < .45:
            candidates.extend(self._map_candidates(rgb, mask))
        if not candidates:
            self.reason = "no_geometric_match"
            return None
        candidates.sort(key=lambda r: r.confidence, reverse=True)
        best = candidates[0]
        center = np.array([rgb.shape[1] / 2, rgb.shape[0] / 2, 1.])
        for other in candidates[1:]:
            if other.confidence >= best.confidence * .85 and np.linalg.norm((best.matrix - other.matrix) @ center) > 20:
                self.reason = "ambiguous_map_match"
                return None
        self.reason = "registered"
        self.last_registration = best
        return best

    def locate(self, rgb, mask, icon_xy, icon: PoseResult, *, now: float) -> PoseResult:
        registration = self.register(rgb, mask)
        if registration is None or not icon.valid:
            self._pending = None
            self._confirmed = False
            return PoseResult.invalid()
        if min(icon.confidence, registration.confidence) < .45:
            self.reason = "low_registration_confidence"
            self._pending = None
            self._confirmed = False
            return PoseResult.invalid()
        matrix = registration.matrix
        x, y = matrix @ np.array([*icon_xy, 1.])
        vector = matrix[:, :2] @ np.array([math.cos(math.radians(icon.yaw_deg)), math.sin(math.radians(icon.yaw_deg))])
        yaw = normalize_angle_deg(math.degrees(math.atan2(vector[1], vector[0])))
        if not (0 <= x < self.width and 0 <= y < self.height):
            self.reason = "outside_map"
            self._confirmed = False
            return PoseResult.invalid()
        pose = PoseResult(
            x / (self.width - 1), y / (self.height - 1), yaw,
            min(icon.confidence, registration.confidence), True,
            icon.blob_area_px, "visual", None, now,
        )
        # Require two consistent independent observations after a miss or respawn.
        previous = self._previous
        if previous is not None:
            dt = now - previous.observed_at
            jump = math.hypot((pose.x_norm - previous.x_norm) * self.width,
                              (pose.y_norm - previous.y_norm) * self.height)
            if dt <= 0 or dt > .5 or jump > 8. + 250. * dt:
                self._confirmed = False
        if not self._confirmed:
            pending = self._pending
            self._pending = pose
            if pending is None or not 0 < now - pending.observed_at <= .5 or math.hypot(pose.x_norm - pending.x_norm, pose.y_norm - pending.y_norm) > .035:
                self.reason = "confirming_position"
                return PoseResult.invalid()
            self._confirmed = True
        self._previous = pose
        self.reason = "measured"
        return pose
