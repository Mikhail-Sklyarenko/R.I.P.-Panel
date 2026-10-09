"""120 Hz camera output with bounded acceleration and a measured-pose deadline.

Command accounting compensates capture latency; it is never a measured pose
and is never used to permit translation. No output survives a 250 ms old pose.
"""
from __future__ import annotations

from collections import deque
import logging
import math
import threading
import time


class CameraServo:
    def __init__(self, move, x360, *, background=False, clock=time.monotonic, allowed=lambda: True):
        if not math.isfinite(x360) or x360 <= 0:
            raise ValueError("x360 must be positive and finite")
        self.move, self.x360, self.clock = move, x360, clock
        self.allowed = allowed
        self._lock = threading.RLock()
        self._shutdown = threading.Event()
        self._thread = None
        self._history = deque()
        self._deadline = 0.
        self._remaining = self._speed = self._fraction = 0.
        self._limit = 100.
        self._deadband = 1.5
        self._responsive = False
        self._last = self.clock()
        if background:
            self._thread = threading.Thread(target=self._run, daemon=True, name="nav-camera-120hz")
            self._thread.start()

    def submit(self, error, observed_at, *, limit=100., responsive=False, deadband_deg=1.5):
        with self._lock:
            now = self.clock()
            if not all(math.isfinite(v) for v in (error, observed_at, limit)) or not 0 <= now-observed_at <= .25:
                self.stop()
                return
            while self._history and self._history[0][0] < now-.5:
                self._history.popleft()
            # At the +/-180 seam, continue an already chosen turn direction.
            if abs(error) > 165 and abs(self._speed) > 10 and error*self._speed < 0:
                error += math.copysign(360., self._speed)
            sent_after_capture = sum(angle for stamp, angle in self._history if stamp >= observed_at)
            self._remaining = error - sent_after_capture
            self._deadline = observed_at + .25
            self._limit = max(1., min(360., limit))
            self._responsive = bool(responsive)
            self._deadband = max(1.5,min(3.,float(deadband_deg)))

    def stop(self):
        with self._lock:
            self._deadline = 0.
            self._remaining = self._speed = self._fraction = 0.
            # Keep recent output history for latency compensation after resume.

    def advance(self):
        with self._lock:
            now = self.clock()
            # Never catch up a scheduler stall with one large mouse jump.
            dt = min(1/60, max(0., now-self._last))
            self._last = now
            if now >= self._deadline or not self.allowed():
                self.stop()
                return
            error = self._remaining
            if abs(error) <= self._deadband:
                self._speed = self._fraction = 0.
                return
            # Braking envelope and proportional tail give an eased arrival.
            acceleration = (3600. if self._responsive else 2160.) if self._limit > 120 else 360.
            gain = (16. if self._responsive else 10.) if self._limit > 120 else 5.
            desired = math.copysign(min(self._limit, math.sqrt(2*acceleration*abs(error)), gain*abs(error)), error)
            self._speed += max(-acceleration*dt, min(acceleration*dt, desired-self._speed))
            angle = self._speed*dt
            if angle*error <= 0:
                return
            angle = math.copysign(min(abs(angle), abs(error)), angle)
            counts = angle*self.x360/360 + self._fraction
            dx = int(counts)
            self._fraction = counts-dx
            if dx:
                self.move(dx, 0)
                emitted = dx*360/self.x360
                self._remaining -= emitted
                self._history.append((now, emitted))
                while self._history and self._history[0][0] < now-.5:
                    self._history.popleft()

    def _run(self):
        while not self._shutdown.wait(1/120):
            try:
                self.advance()
            except Exception:
                self.stop()
                logging.getLogger("CS2Bot.nav").exception("Camera output failed; servo stopped")
                return

    def close(self):
        self._shutdown.set()
        self.stop()
        if self._thread is not None:
            self._thread.join(timeout=.2)
