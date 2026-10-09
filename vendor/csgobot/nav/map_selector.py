"""Identify supported maps from radar geometry when no map-name HUD is visible."""
import cv2
import numpy as np
from nav.visual_localizer import VisualLocalizer
from nav.minimap_reader import MinimapReader
from nav.hud_mask import exclude_range_ring


class VisualMapSelector:
    def __init__(self, calibration):
        self.reader = MinimapReader(calibration)
        self.localizers = None
        self.next_at = 0.
        self.pending = None
        self.count = 0
        self.last_scores = {}

    def confirm(self, scores):
        ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
        if not ranked or ranked[0][1] < .72 or (len(ranked) > 1 and ranked[0][1] - ranked[1][1] < .10):
            self.pending, self.count = None, 0
            return None
        winner = ranked[0][0]
        self.count = self.count + 1 if winner == self.pending else 1
        self.pending = winner
        return winner if self.count >= 3 else None

    def update(self, frame, *, now):
        if now < self.next_at:
            return None
        self.next_at = now + 2.
        if self.localizers is None:
            self.localizers = {name: VisualLocalizer(name) for name in ('de_dust2', 'de_mirage', 'de_inferno', 'de_vertigo', 'de_cache')}
        self.reader.read(frame)
        if self.reader.last_circle is None:
            return self.confirm({})
        crop, cx, cy, radius = self.reader._crop_from_circle(frame, self.reader.last_circle)
        yy, xx = np.ogrid[:crop.shape[0], :crop.shape[1]]
        d = (xx-cx)**2 + (yy-cy)**2
        mask = np.uint8((d < (radius-8)**2) & (d > 22**2))*255
        saturated = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)[:, :, 1] > 160
        mask[cv2.dilate(np.uint8(saturated), np.ones((7, 7), np.uint8)) > 0] = 0
        scores = {}
        for name, localizer in self.localizers.items():
            evidence = (exclude_range_ring(mask.copy(), cx, cy, radius)
                        if name in ("de_inferno", "de_vertigo", "de_cache", "de_mirage", "de_dust2") else mask)
            match = localizer.register(crop, evidence)
            if match is not None and match.inliers >= 10:
                scores[name] = match.confidence
        self.last_scores = scores
        return self.confirm(scores)


class AsyncVisualMapSelector:
    """Latest-only geometry discovery; enemies never starve map identification.

    Results select a map name only. Navigation still needs a fresh measured pose.
    Reset generations and a result deadline discard work from earlier sessions.
    """
    def __init__(self, calibration, *, selector_factory=VisualMapSelector):
        import threading
        self._calibration = calibration
        self._factory = selector_factory
        self._condition = threading.Condition()
        self._closed = False
        self._generation = 0
        self._job = self._result = None
        self._active = False
        self.next_at = 0.
        self.status = 'idle'
        self._thread = threading.Thread(target=self._run, daemon=True, name='nav-map-discovery')
        self._thread.start()

    def update(self, frame, *, now):
        candidate = None
        with self._condition:
            if self._closed:
                return None
            self._active = True
            if self._result is not None:
                generation, observed, winner = self._result
                self._result = None
                if generation == self._generation and 0 <= now-observed <= 8.:
                    candidate = winner
            if now >= self.next_at:
                self.next_at = now + 1.
                self._job = (self._generation, now, frame.copy())
                self._condition.notify()
        return candidate

    def reset(self):
        with self._condition:
            if not self._active:
                return
            self._active = False
            self._generation += 1
            self._job = self._result = None
            self.next_at = 0.
            self.status = 'idle'

    def _run(self):
        import logging
        scanner = self._factory(self._calibration)
        scanner_generation = None
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._job is not None)
                if self._closed:
                    return
                generation, observed, frame = self._job
                self._job = None
            if scanner_generation != generation:
                scanner.pending, scanner.count, scanner.next_at = None, 0, 0.
                scanner_generation = generation
            try:
                # The outer latest-only queue owns scheduling, not scanner cadence.
                scanner.next_at = 0.
                winner = scanner.update(frame, now=observed)
                scores = getattr(scanner, 'last_scores', {})
                status = f'{scanner.pending or "unknown"}:{scanner.count}/3 scores={scores}'
            except Exception:
                logging.getLogger('CS2Bot.nav').exception('Map discovery failed')
                winner, status = None, 'geometry_error'
            with self._condition:
                if generation == self._generation and not self._closed:
                    self.status = status
                    if winner is not None:
                        self._result = (generation, observed, winner)

    def close(self):
        with self._condition:
            self._closed = True
            self._job = self._result = None
            self._condition.notify()
        self._thread.join(timeout=2.)
