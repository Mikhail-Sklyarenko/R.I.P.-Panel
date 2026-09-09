"""Runtime adapter: observed radar geometry -> fresh measured map pose."""
from __future__ import annotations

import logging
import time
from dataclasses import replace

import cv2
import numpy as np

from nav.perception import PerceptionResult
from nav.pose import PoseResult
from nav.visual_localizer import VisualLocalizer
from nav.icon_heading import observe_heading


class VisualPerception:
    def __init__(self, reader, localizer, yaw=None, **_compat):
        self.reader, self.localizer = reader, localizer
        self._last_log = 0.
        self.reload_map(localizer.map_id)

    def reload_map(self, map_id):
        self.visual = VisualLocalizer(map_id)
        self.reason = "not_observed"
        self._cached = None
        self._next_at = 0.

    def reset(self):
        self.visual.reset()
        self._cached = None
        self._next_at = 0.

    def update(self, frame, *, now=None, **_ignored_targets):
        ts = time.monotonic() if now is None else now
        if self._cached is not None and ts < self._next_at:
            return self._cached
        self._next_at = ts + .08
        icon = self.reader.read(frame)
        pose = PoseResult.invalid()
        circle = self.reader.last_circle
        if icon.valid and circle is not None and self.reader.last_icon_xy is not None:
            crop, cx, cy, radius = self.reader._crop_from_circle(frame, circle)
            yy, xx = np.ogrid[:crop.shape[0], :crop.shape[1]]
            distance = (xx - cx)**2 + (yy - cy)**2
            mask = np.uint8((distance < (radius - 7)**2) & (distance > 22**2)) * 255
            colored = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)[:, :, 1] > 160
            colored = cv2.dilate(np.uint8(colored), np.ones((7, 7), np.uint8)) > 0
            mask[colored] = 0
            heading = observe_heading(crop, self.reader.last_icon_component)
            if heading is None:
                self.visual.reset()
                self.reason = "ambiguous_icon_heading"
            else:
                icon = replace(icon, yaw_deg=heading[0], confidence=min(icon.confidence, heading[1]))
                pose = self.visual.locate(crop, mask, self.reader.last_icon_xy, icon, now=ts)
                self.reason = self.visual.reason
        else:
            self.visual.reset()
            self.reason = "no_player_icon"
        # Place recognition is metadata only, never a replacement for map XY.
        place = None
        if pose.valid and self.localizer.ready:
            place = self.localizer.localize(frame, circle)
            if place is not None:
                pose = replace(pose, place_id=place.place_id)
        self._cached = PerceptionResult(icon, place, pose)
        if ts - self._last_log >= 2.:
            logging.getLogger("CS2Bot.nav").info("nav: perception=%s confidence=%.2f", self.reason, pose.confidence)
            self._last_log = ts
        return self._cached
