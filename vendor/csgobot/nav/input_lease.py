"""Expire navigation's held keys even when inference or capture stops ticking."""
from __future__ import annotations

import threading
import time


class KeyLease:
    def __init__(self, key_down, key_up, *, background=False, clock=time.monotonic):
        self._down, self._up, self.clock = key_down, key_up, clock
        self._keys = set()
        self._deadline = 0.
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        if background:
            self._thread = threading.Thread(target=self._watch, daemon=True, name="nav-key-lease")
            self._thread.start()

    @property
    def active(self):
        with self._lock:
            return self.clock() < self._deadline

    @property
    def keys(self):
        with self._lock:
            return set(self._keys)

    def renew(self, duration):
        with self._lock:
            self._deadline = self.clock() + max(0., duration)

    def set_keys(self, keys):
        with self._lock:
            wanted = set(keys) if self.clock() < self._deadline else set()
            for key in sorted(self._keys - wanted):
                self._up(key)
                self._keys.remove(key)
            for key in sorted(wanted - self._keys):
                self._down(key)
                self._keys.add(key)

    def release(self):
        with self._lock:
            self._deadline = 0.
            self.set_keys(set())

    def expire(self):
        with self._lock:
            if self.clock() >= self._deadline:
                self.release()

    def _watch(self):
        while not self._stop.wait(.02):
            self.expire()

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=.2)
        self.release()
