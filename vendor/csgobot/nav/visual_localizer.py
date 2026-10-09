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
from nav.reference_tracker import ReferenceTracker


@dataclass(frozen=True)
class Registration:
    matrix: np.ndarray
    confidence: float
    inliers: int
    residual_px: float
    source: str
    layer_id: str | None = None


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
        self._reference_images = {}
        self._live_anchors = []
        self._last_anchor_at = float('-inf')
        self.reason = "not_observed"
        self.last_registration = None
        self._previous = None
        self._pending = None
        self._confirmed = False
        self._pyramid = None
        self._dense = None
        self._layered = None
        self._tracker = ReferenceTracker()
        if map_id!="de_nuke_ramp":
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
            self._reference_images[name] = (rgb.copy(), to_map.copy())

    def reset(self):
        self._previous = self._pending = None
        self._confirmed = False
        self.last_registration = None
        self._tracker.anchor = None

    def _remember_observation(self, rgb, mask, registration, now):
        if self.map_id in ("de_vertigo", "de_nuke"):
            return  # Never insert lower-floor live anchors into the upper atlas.
        # Only original calibrated references can anchor a new live view.
        # Never chain observed->observed transforms or integrate camera input.
        if (registration.confidence < .70 or registration.source.startswith("observed:")
                or now-self._last_anchor_at < 1.):
            return
        matrix = registration.matrix
        center = matrix @ np.array([rgb.shape[1]/2, rgb.shape[0]/2, 1.])
        angle = math.degrees(math.atan2(matrix[1, 0], matrix[0, 0]))
        if any(np.linalg.norm(center-p) < 15 and abs(normalize_angle_deg(angle-a)) < 25
               for _, p, a in self._live_anchors):
            return
        self._last_anchor_at = now
        name = f"observed:{now:.6f}"
        clean = rgb.copy()
        clean[mask == 0] = 0
        self.add_reference(clean, matrix, name)
        self._live_anchors.append((name, center, angle))
        if len(self._live_anchors) > 8:
            old, _, _ = self._live_anchors.pop(0)
            self.references = [ref for ref in self.references if ref[0] != old]
            self._reference_images.pop(old, None)

    def _edge_agreement(self, rgb, mask, matrix, reference_rgb=None):
        """Validate a proposed transform using wall pixels not descriptor votes.

        A low descriptor inlier ratio is common across render styles. It is
        never accepted on that basis alone: contours must agree in both
        directions and be spread over the radar.
        """
        projected = cv2.warpAffine(
            self.map_rgb if reference_rgb is None else reference_rgb, matrix, (rgb.shape[1], rgb.shape[0]),
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
        # At the edge of a map the empty half of the radar contains no walls.
        # Two quadrants are sufficient only with broad 2-D contour support.
        sy, sx = np.nonzero(support)
        broad = (len(sx) >= 120 and np.ptp(sx) >= w*.35 and np.ptp(sy) >= h*.35
                 and cv2.contourArea(cv2.convexHull(np.float32(np.column_stack((sx,sy))))) >= h*w*.12)
        if recall < .78 or precision < .50 or (covered < 3 and not (covered >= 2 and broad)):
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
        if self.map_id in ('de_vertigo', 'de_nuke'):
            if self._layered is None:
                from nav.layered_localizer import LayeredLocalizer
                if self.map_id=="de_nuke":
                    from nav.nuke_localizer import NukeLocalizer
                    self._layered=NukeLocalizer(self)
                else:self._layered = LayeredLocalizer(self)
            result = self._layered.register(rgb,mask)
            self.last_registration = result
            self.reason = 'registered' if result else 'ambiguous_or_missing_floor'
            return result
        return self._register_single(rgb,mask)

    def _register_single(self, rgb, mask) -> Registration | None:
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
            if self.map_id=="de_nuke_ramp":
                # These references are calibrated north-up at a fixed HUD zoom.
                # A free similarity fit on repetitive ramp rails can drift in
                # scale while retaining a deceptively small feature residual.
                basis=np.eye(2)/.355
                offset=np.median(dst[good]-src[good]@basis.T,axis=0)
                matrix=np.column_stack((basis,offset))
                good=np.linalg.norm(src@basis.T+offset-dst,axis=1)<=3.
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
            agreement = None
            if confidence < .6 and name != "radar":
                # Sparse SIFT votes alone remain insufficient. Verify the fit
                # against independent wall contours in the same HUD style.
                reference_rgb, to_map = self._reference_images[name]
                inverse = cv2.invertAffineTransform(to_map)
                to_reference = np.column_stack((inverse[:, :2] @ matrix[:, :2],
                                                 inverse[:, :2] @ matrix[:, 2] + inverse[:, 2]))
                agreement = self._edge_agreement(rgb, mask, to_reference, reference_rgb)
                if agreement is not None:
                    confidence = max(confidence, agreement)
            candidates.append(Registration(matrix, confidence, n, error, name))
        if self.map_id!="de_nuke_ramp" and (not candidates or max(c.confidence for c in candidates) < .45):
            candidates.extend(self._map_candidates(rgb, mask))
        if self.map_id!="de_nuke_ramp" and (not candidates or max(c.confidence for c in candidates) < .70):
            if self._dense is None:
                from nav.dense_localizer import DenseMapMatcher
                self._dense = DenseMapMatcher(self.map_rgb, translucent=self.map_id in ("de_inferno","de_vertigo","de_vertigo_lower","de_nuke","de_nuke_lower","de_cache","de_mirage","de_dust2"), rich_hud=self.map_id == "de_dust2", inferno_hud=self.map_id == "de_inferno")
            dense = self._dense.match(rgb,mask)
            if dense is not None:
                matrix,confidence,support = dense
                candidates.append(Registration(matrix,confidence,support,0.,"global_contours"))
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
        if self.map_id not in ("de_vertigo", "de_nuke") and icon.valid and self.reason != "ambiguous_map_match" and (registration is None or registration.confidence < .6):
            tracked = self._tracker.track(rgb, mask, now)
            if tracked is not None:
                matrix, confidence, count, residual = tracked
                center = np.array([*icon_xy, 1.])
                if (registration is not None and registration.confidence >= .45
                        and np.linalg.norm((registration.matrix-matrix) @ center) > 20):
                    self.reason = "ambiguous_map_match"
                    self._confirmed = False
                    self._pending = None
                    return PoseResult.invalid()
                registration = Registration(matrix, confidence, count, residual, "fixed_frame_track")
                self.last_registration = registration
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
            icon.blob_area_px, "visual", None, now, registration.layer_id,
        )
        # Require two consistent independent observations after a miss or respawn.
        previous = self._previous
        if previous is not None:
            dt = now - previous.observed_at
            jump = math.hypot((pose.x_norm - previous.x_norm) * self.width,
                              (pose.y_norm - previous.y_norm) * self.height)
            if dt <= 0 or dt > .5 or jump > 8. + 250. * dt or pose.layer_id != previous.layer_id:
                self._confirmed = False
        if not self._confirmed:
            pending = self._pending
            self._pending = pose
            if pending is None or pending.layer_id != pose.layer_id or not 0 < now - pending.observed_at <= .5 or math.hypot(pose.x_norm - pending.x_norm, pose.y_norm - pending.y_norm) > .035:
                self.reason = "confirming_position"
                return PoseResult.invalid()
            self._confirmed = True
        self._previous = pose
        self.reason = "measured"
        if registration.source != "fixed_frame_track":
            self._remember_observation(rgb, mask, registration, now)
            if registration.confidence >= .70 and not registration.source.startswith("observed:"):
                self._tracker.seed(rgb, mask, registration.matrix, now)
        return pose
