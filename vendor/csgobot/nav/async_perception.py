"""Slow atlas registration off the control loop; current frames supply every pose.

The worker returns a measured image anchor, never a movement prediction. The
foreground validates fresh radar pixels against that fixed anchor using optical
flow. A recent atlas measurement may bridge a miss only until its original
250 ms deadline. Mouse accounting cannot grant motion.
"""
import logging
import json
import math
import threading
import time
import cv2
import numpy as np
from nav.hud_mask import exclude_range_ring
from nav.coords import normalize_angle_deg
from nav.icon_heading import observe_heading
from nav.perception import PerceptionResult
from nav.pose import PoseResult
from nav.reference_tracker import DenseReferenceTracker as ReferenceTracker
from nav.reference_tracker import ReferenceTracker as SparseReferenceTracker
from nav.visual_localizer import VisualLocalizer, Registration
from nav.paths import resolve_map_radar_path, resolve_visual_profile_file
from nav.walkable import read_grayscale


class AsyncVisualPerception:
    def __init__(self, reader, localizer, *, visual_profile=None):
        self.reader, self.localizer = reader, localizer
        self.profile = visual_profile
        self._condition = threading.Condition()
        self._closed = False
        self._generation = 0
        self._job = self._result = None
        self._last_log = 0.
        self.registration_status = "starting"
        self.registration_ms = 0.
        self.registration_confidence = 0.
        self.reload_map(localizer.map_id)
        self._thread = threading.Thread(target=self._run, daemon=True, name='nav-atlas-registration')
        self._thread.start()

    def reload_map(self, map_id):
        radar = read_grayscale(resolve_map_radar_path(map_id))
        with self._condition:
            self.map_id = map_id
            self.height, self.width = radar.shape
            self._generation += 1
            self._job = self._result = None
            self._rejected_at = float("-inf")
        self._tracker = ReferenceTracker(reduced_alignment=self.map_id == "de_dust2")
        self._seed_at = None
        self._seed_layer = None
        self._previous = None
        self._accepted = None
        self.reason = 'waiting_visual_anchor'
        self._dense_scale = None
        self._dense_fast = None
        self._hud_fast = None
        self.motion_hint = None
        self.door_observation = None
        self._heading_alignment = None
        from nav.mirage_levels import MirageLevels
        self._mirage_levels = MirageLevels() if map_id == "de_mirage" else None
        from nav.cache_levels import CacheLevels
        self._cache_levels = CacheLevels() if map_id == "de_cache" else None
        # This is a calibrated HUD zoom hint, never a player position. Every
        # result must still uniquely match current pixels anywhere on the map.
        metadata = resolve_visual_profile_file(map_id, "navigation.json")
        if metadata.is_file():
            hint = json.loads(metadata.read_text(encoding="utf-8")).get("initial_hud_scale")
            if isinstance(hint, (int, float)) and math.isfinite(hint) and .15 <= hint <= .50:
                self._dense_scale = float(hint)
        self.registration_status = "starting"
        self.registration_confidence = 0.
        self.registration_ms = 0.

    def reset(self):
        self.reload_map(self.map_id)

    def _run(self):
        scanner = None
        scanner_map = None
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._job is not None)
                if self._closed: return
                generation, map_id, raw, raw_mask, stamp, icon, xy, heading, crop, mask, canonical = self._job
                self._job = None
            try:
                if scanner_map != map_id:
                    scanner = VisualLocalizer(map_id, profile_dir=self.profile)
                    scanner_map = map_id
                started = time.perf_counter()
                registration = scanner.register(raw, raw_mask)
                self.registration_ms = (time.perf_counter()-started)*1000
                self.registration_status = getattr(scanner, 'reason', 'registered')
                self.registration_confidence = registration.confidence if registration is not None else 0.
                raw_scale = (1./np.linalg.norm(registration.matrix[:,0])
                    if registration is not None and getattr(registration,'source','')=='global_contours' else None)
                if registration is not None:
                    inverse = cv2.invertAffineTransform(canonical)
                    matrix = np.column_stack((registration.matrix[:,:2] @ inverse[:,:2],
                                              registration.matrix[:,:2] @ inverse[:,2]+registration.matrix[:,2]))
                    registration = Registration(matrix, registration.confidence,
                        getattr(registration,'inliers',0), getattr(registration,'residual_px',0.),
                        getattr(registration,'source','atlas'), getattr(registration,'layer_id',None))
                if registration is not None and registration.confidence >= .70:
                    with self._condition:
                        if generation == self._generation and not self._closed:
                            self._result = (generation, stamp, crop, mask, registration, icon, xy, heading)
                            if raw_scale is not None:
                                self._dense_scale = raw_scale
                elif getattr(scanner, 'reason', '') == 'ambiguous_map_match':
                    with self._condition:
                        if generation == self._generation:
                            self._result = None
                            self._rejected_at = stamp
            except Exception:
                logging.getLogger('CS2Bot.nav').exception('Atlas registration failed')
                with self._condition:
                    if generation == self._generation: self._result = None

    def _current_registration(self, crop, mask, stamp, *, sparse_only=False):
        with self._condition:
            result = self._result
            rejected_at = self._rejected_at
        if self._seed_at is not None and rejected_at >= self._seed_at:
            self._tracker = ReferenceTracker(reduced_alignment=self.map_id == "de_dust2")
            self._seed_at = None
            self._previous = self._accepted = None
        if result is not None:
            generation, observed, reference, reference_mask, registration, _, _, _ = result
            if generation == self._generation and 0 <= stamp-observed <= 6. and (self._seed_at is None or observed > self._seed_at):
                self._tracker.seed(reference, reference_mask, registration.matrix, observed)
                self._seed_at = observed
                self._seed_layer = getattr(registration, 'layer_id', None)
                if observed == stamp:
                    return registration.matrix, registration.confidence
        tracked = (SparseReferenceTracker.track(self._tracker, crop, mask, stamp)
                   if sparse_only else self._tracker.track(crop, mask, stamp))
        if tracked is None: return None
        return tracked[0], tracked[1]

    def update(self, frame, *, now=None, allow_global=True, **_):
        stamp = time.monotonic() if now is None else now
        self.motion_hint = None
        self.door_observation = None
        from nav.door_actions import observe_door
        self.door_observation = observe_door(frame,self.map_id,stamp)
        icon = self.reader.read(frame)
        pose = PoseResult.invalid()
        self.reason = 'no_player_icon'
        circle = self.reader.last_circle
        if icon.valid and circle is not None and self.reader.last_icon_xy is not None:
            crop,cx,cy,radius = self.reader._crop_from_circle(frame,circle)
            heading = getattr(self.reader,"last_heading",None) or observe_heading(crop,self.reader.last_icon_component)
            if (self.map_id == 'de_dust2' and heading is not None and heading[1]>=.9
                    and icon.confidence>=.75 and self._heading_alignment is not None):
                from nav.motion_continuity import HeadingObservation
                self.motion_hint=HeadingObservation(normalize_angle_deg(heading[0]+self._heading_alignment),stamp,self.map_id)
            raw = crop
            yy,xx = np.ogrid[:raw.shape[0],:raw.shape[1]]
            distance = (xx-cx)**2+(yy-cy)**2
            raw_mask = np.uint8((distance<(radius-7)**2)&(distance>22**2))*255
            saturated = cv2.cvtColor(raw,cv2.COLOR_RGB2HSV)[:,:,1]>160
            raw_mask[cv2.dilate(np.uint8(saturated),np.ones((7,7),np.uint8))>0] = 0
            hud_mask = raw_mask.copy() if self.map_id == "de_dust2" else None
            if self.map_id in ("de_inferno", "de_vertigo", "de_nuke", "de_cache", "de_mirage", "de_dust2"):
                exclude_range_ring(raw_mask, cx, cy, radius)
            # Circle estimates move by a pixel between frames. Register and
            # track in one stable coordinate system, preserving measured XY.
            scale = 120. / radius
            canonical = np.array([[scale,0.,128.-cx*scale],[0.,scale,128.-cy*scale]])
            xy = canonical @ np.array([*self.reader.last_icon_xy,1.])
            crop = cv2.warpAffine(crop,canonical,(256,256))
            cx = cy = 128.
            radius = 120.
            yy,xx = np.ogrid[:crop.shape[0],:crop.shape[1]]
            distance = (xx-cx)**2+(yy-cy)**2
            mask = np.uint8((distance<(radius-7)**2)&(distance>22**2))*255
            saturated = cv2.cvtColor(crop,cv2.COLOR_RGB2HSV)[:,:,1]>160
            mask[cv2.dilate(np.uint8(saturated),np.ones((7,7),np.uint8))>0] = 0
            if self.map_id in ("de_inferno", "de_vertigo", "de_nuke", "de_cache", "de_mirage", "de_dust2"):
                exclude_range_ring(mask, cx, cy, radius)
            if heading is not None and self.map_id not in ("de_inferno", "de_vertigo", "de_nuke", "de_cache", "de_mirage", "de_dust2"):
                with self._condition:
                    self._job = (self._generation,self.map_id,raw.copy(),raw_mask.copy(),stamp,
                                 icon, xy, heading, crop.copy(),mask.copy(),canonical)
                    self._condition.notify()
            measured_layer = self._seed_layer
            measurement_source = 'measured_fixed_anchor'
            # Inferno often has scene noise under the translucent HUD. Try the
            # cheaper unique whole-map measurement before iterative ECC there.
            measured = (None if self.map_id in ("de_inferno", "de_vertigo", "de_nuke", "de_cache", "de_mirage", "de_dust2") else
                        self._current_registration(crop,mask,stamp))
            if self.map_id == "de_nuke" and heading is not None and self._dense_fast is not None:
                self._dense_fast.player_xy=self.reader.last_icon_xy
                measured=self._current_registration(crop,mask,stamp,sparse_only=not allow_global)
                measured_layer=self._seed_layer
                if measured is not None:
                    m=measured[0]
                    raw_matrix=np.column_stack((m[:,:2]@canonical[:,:2],m[:,:2]@canonical[:,2]+m[:,2]))
                    if not self._dense_fast.confirms_layer(raw,raw_mask,raw_matrix,measured_layer):
                        measured=None
            if allow_global and measured is None and heading is not None and self._dense_scale is not None:
                # Once zoom is known, a whole-map contour check is cheap enough
                # for the current frame. It supplies a new measurement, not a
                # projected position, and does not restrict random spawn XY.
                if self._dense_fast is None:
                    from nav.dense_localizer import DenseMapMatcher
                    payload=resolve_map_radar_path(self.map_id).read_bytes()
                    bgr=cv2.imdecode(np.frombuffer(payload,dtype=np.uint8),cv2.IMREAD_COLOR)
                    if self.map_id == 'de_nuke':
                        from nav.nuke_localizer import NukeDenseMatcher
                        self._dense_fast = NukeDenseMatcher(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB))
                    elif self.map_id == 'de_vertigo':
                        from nav.layered_localizer import LayeredDenseMatcher
                        self._dense_fast = LayeredDenseMatcher(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB))
                    else:
                        self._dense_fast=DenseMapMatcher(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB),
                            translucent=self.map_id in ('de_inferno', 'de_cache', 'de_mirage', 'de_dust2'),
                            rich_hud=self.map_id == 'de_dust2', inferno_hud=self.map_id == 'de_inferno')
                if self.map_id=="de_nuke":self._dense_fast.player_xy=self.reader.last_icon_xy
                fast=self._dense_fast.match_at_scale(raw,raw_mask,self._dense_scale)
                if fast is not None:
                    measurement_source = 'measured_global_contours'
                    measured_layer = getattr(self._dense_fast,'last_layer',None)
                    matrix,confidence,_=fast
                    inverse=cv2.invertAffineTransform(canonical)
                    measured=(np.column_stack((matrix[:,:2]@inverse[:,:2],
                        matrix[:,:2]@inverse[:,2]+matrix[:,2])),confidence)
                    if self.map_id in ('de_inferno', 'de_vertigo', 'de_nuke', 'de_cache', 'de_mirage', 'de_dust2'):
                        # A fresh globally verified image is an independent
                        # anchor. Never replace it later with an older worker
                        # result, and never seed from a propagated/tracked pose.
                        if self._seed_at is None or stamp-self._seed_at >= .3 or measured_layer != self._seed_layer:
                            self._tracker.seed(crop,mask,measured[0],stamp)
                            self._seed_at,self._seed_layer = stamp,measured_layer
                        with self._condition:
                            self._job = None
            if (self.map_id == 'de_dust2' and allow_global and measured is None
                    and heading is not None and self._dense_scale is not None):
                from nav.hud_atlas_matcher import HudAtlasMatcher
                if self._hud_fast is None:
                    self._hud_fast=HudAtlasMatcher(self.map_id,(self.height,self.width),self.profile)
                hud=self._hud_fast.match_at_scale(raw,hud_mask,self._dense_scale)
                if hud is not None:
                    matrix,confidence,_=hud
                    inverse=cv2.invertAffineTransform(canonical)
                    measured=(np.column_stack((matrix[:,:2]@inverse[:,:2],
                        matrix[:,:2]@inverse[:,2]+matrix[:,2])),confidence)
                    measured_layer=None
                    measurement_source='measured_hud_atlas_contours'
                    self._tracker.seed(crop,mask,measured[0],stamp)
                    self._seed_at,self._seed_layer=stamp,None
                    with self._condition:
                        self._job=None
            if measured is None and self.map_id in ("de_inferno", "de_vertigo", "de_nuke", "de_cache", "de_mirage", "de_dust2"):
                measured = self._current_registration(crop, mask, stamp,
                    sparse_only=not allow_global)
                measured_layer = self._seed_layer
                if measured is not None and self.map_id in ('de_vertigo','de_nuke'):
                    # A fixed anchor must not carry its old floor across a shaft
                    # or stairs. Recheck current appearance on both floor maps.
                    m = measured[0]
                    raw_matrix = np.column_stack((m[:,:2]@canonical[:,:2],m[:,:2]@canonical[:,2]+m[:,2]))
                    if self._dense_fast is None or not self._dense_fast.confirms_layer(raw,raw_mask,raw_matrix,measured_layer):
                        measured = None
            if self.map_id in ('de_inferno', 'de_vertigo', 'de_nuke', 'de_cache', 'de_mirage', 'de_dust2') and measured is None and heading is not None:
                # Atlas search is recovery work. Running the same full-map
                # search concurrently on every successful frame doubles CPU
                # load and can make both measurements miss the input deadline.
                with self._condition:
                    self._job = (self._generation,self.map_id,raw.copy(),raw_mask.copy(),stamp,
                                 icon,xy,heading,crop.copy(),mask.copy(),canonical)
                    self._condition.notify()
            observed = stamp
            tracked = measured is not None
            if measured is None and heading is not None:
                # A completed registration remains a measurement of its ORIGINAL
                # frame. Never relabel it with the current capture timestamp.
                with self._condition:
                    result = self._result
                if result is not None and result[0] == self._generation and 0 <= stamp-result[1] <= .25:
                    _, observed, _, _, registration, icon, xy, heading = result
                    measured = registration.matrix, registration.confidence
                    measured_layer = getattr(registration, 'layer_id', None)
            self.reason = 'waiting_visual_anchor' if measured is None else 'ambiguous_icon_heading'
            if measured is not None and heading is not None:
                matrix, confidence = measured
                confidence = min(confidence,icon.confidence,heading[1])
                x,y = matrix @ np.array([*xy,1.])
                vector = matrix[:,:2] @ np.array([math.cos(math.radians(heading[0])),math.sin(math.radians(heading[0]))])
                yaw = normalize_angle_deg(math.degrees(math.atan2(vector[1],vector[0])))
                if observed==stamp and confidence>=.75:
                    self._heading_alignment=normalize_angle_deg(yaw-heading[0])
                    if self.map_id=='de_dust2' and heading[1]>=.9:
                        from nav.motion_continuity import HeadingObservation
                        self.motion_hint=HeadingObservation(yaw,stamp,self.map_id)
                if confidence >= .45 and 0<=x<self.width and 0<=y<self.height:
                    measured_pose = PoseResult(x/(self.width-1),y/(self.height-1),yaw,confidence,True,icon.blob_area_px,'visual',None,observed,measured_layer)
                    previous = self._previous
                    if previous is None or observed > previous.observed_at:
                        self._previous = measured_pose
                    if (previous is not None and previous.layer_id == measured_pose.layer_id and 0<observed-previous.observed_at<=.5
                            and math.hypot((measured_pose.x_norm-previous.x_norm)*self.width,
                                           (measured_pose.y_norm-previous.y_norm)*self.height)<=8+250*(observed-previous.observed_at)):
                        pose = measured_pose
                        self._accepted = pose
                        self.reason = measurement_source if tracked else 'measured_atlas_frame'
                    elif (self._accepted is not None and observed <= self._accepted.observed_at
                          and 0 <= stamp-self._accepted.observed_at <= .25):
                        pose = self._accepted
                        self.reason = 'measured_atlas_frame'
                    else:
                        self._accepted = None
                        self.reason = 'confirming_position'
                else: self.reason = 'low_registration_confidence'
        if (self.reason in ('waiting_visual_anchor','ambiguous_icon_heading') and self._accepted is not None
                and 0 <= stamp-self._accepted.observed_at <= .25):
            pose = self._accepted
            self.reason = 'measured_pose_within_deadline'
        if self.reason == 'no_player_icon':
            if self._mirage_levels is not None:self._mirage_levels.reset()
            self._previous = self._accepted = None
            self._tracker = ReferenceTracker(reduced_alignment=self.map_id == "de_dust2")
            self._seed_at = None
            with self._condition:
                self._generation += 1
                self._job = self._result = None
        if pose.valid and self._mirage_levels is not None:
            from dataclasses import replace
            layer=self._mirage_levels.classify(frame,(pose.x_norm,pose.y_norm),stamp)
            pose=replace(pose,layer_id=layer or 'unknown')
        if pose.valid and self._cache_levels is not None:
            from dataclasses import replace
            layer=self._cache_levels.classify(frame,(pose.x_norm,pose.y_norm),stamp)
            pose=replace(pose,layer_id=layer or 'unknown')
        if stamp-self._last_log>=2:
            logging.getLogger('CS2Bot.nav').info('nav: perception=%s confidence=%.2f atlas=%s atlas_conf=%.2f atlas_ms=%.0f layer=%s',self.reason,pose.confidence,self.registration_status,self.registration_confidence,self.registration_ms,pose.layer_id or 'none')
            self._last_log=stamp
        if self.reason in ("no_player_icon","confirming_position","low_registration_confidence"):
            self.motion_hint=None
        return PerceptionResult(icon,None,pose)

    def close(self):
        with self._condition:
            self._closed = True
            self._job = None
            self._condition.notify()
        self._thread.join(timeout=2)
