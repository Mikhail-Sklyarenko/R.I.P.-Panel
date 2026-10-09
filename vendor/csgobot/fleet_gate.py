"""Fleet admission lease + cooperative stop for the csgobot worker.

The fleet agent writes CSGOBOT_ADMISSION_FILE ({"attempt_id", "expires_at"} in
wall time) while the coordinator admits gameplay, and creates CSGOBOT_STOP_FILE
to request a clean shutdown (so `finally` blocks release every key). Without
these variables (DM / standalone) the gate is always open.
"""
from __future__ import annotations

import json
import os
import time


class FleetGate:
    CACHE_SEC = 0.1

    def __init__(self, admission_path: str | None = None, stop_path: str | None = None):
        self.admission_path = admission_path if admission_path is not None else os.environ.get(
            "CSGOBOT_ADMISSION_FILE", "")
        self.stop_path = stop_path if stop_path is not None else os.environ.get("CSGOBOT_STOP_FILE", "")
        self.attempt_id = os.environ.get("CSGOBOT_ATTEMPT_ID", "")
        self._checked = 0.0
        self._admitted = not self.admission_path

    @property
    def enabled(self) -> bool:
        return bool(self.admission_path)

    def admitted(self) -> bool:
        if not self.admission_path:
            return True
        now = time.monotonic()
        if now - self._checked >= self.CACHE_SEC:
            self._checked = now
            self._admitted = self._read()
        return self._admitted

    def _read(self) -> bool:
        try:
            with open(self.admission_path, encoding="utf-8") as fh:
                lease = json.load(fh)
        except (OSError, ValueError):
            return False
        if self.attempt_id and lease.get("attempt_id") != self.attempt_id:
            return False
        try:
            return time.time() < float(lease.get("expires_at", 0))
        except (TypeError, ValueError):
            return False

    def stop_requested(self) -> bool:
        return bool(self.stop_path) and os.path.exists(self.stop_path)


_GATE: FleetGate | None = None


def gate() -> FleetGate:
    global _GATE
    if _GATE is None:
        _GATE = FleetGate()
    return _GATE
