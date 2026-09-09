"""Observe the pale direction tip attached to a colored player marker.

The colored body can be nearly circular. Its farthest pixel is not a reliable
heading. Without a distinct attached tip, report uncertainty instead of yaw.
"""
from __future__ import annotations

import math
import cv2
import numpy as np


def observe_heading(rgb, body):
    ys, xs = np.where(body)
    if len(xs) < 5:
        return None
    cx, cy = float(xs.mean()), float(ys.mean())
    values = rgb.astype(np.int16)
    pale = (values.min(axis=2) >= 175) & ((values.max(axis=2) - values.min(axis=2)) <= 80)
    nearby = cv2.dilate(np.uint8(body), np.ones((7, 7), np.uint8)) > 0
    yy, xx = np.ogrid[:body.shape[0], :body.shape[1]]
    radius = math.sqrt(len(xs) / math.pi) + 4
    tips = pale & nearby & ~body & ((xx-cx)**2 + (yy-cy)**2 <= radius**2)
    ty, tx = np.where(tips)
    if len(tx) < 2:
        return None
    dx, dy = float(tx.mean()) - cx, float(ty.mean()) - cy
    distance = math.hypot(dx, dy)
    spread = float(np.mean(np.hypot(tx - cx, ty - cy)))
    if distance < 2. or distance / max(spread, 1.) < .8:
        return None
    return math.degrees(math.atan2(dy, dx)), min(1., distance / max(spread, 1.))
