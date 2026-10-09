"""Blocking preflight: every check must pass before the pair may act.

Unlike `core.startup_checks` (warnings only), a failed check here keeps the
pair in PREFLIGHT with its code visible in the panel. Expensive checks are
cached; they are re-run on demand (PREFLIGHT command) or after the TTL.
"""
from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

CheckFn = Callable[[], tuple[bool, str]]
REQUIRED_CLIENT = (1280, 720)
# Checks at or below this TTL may run on the observation path. Heavier checks
# stay cached until a PREFLIGHT command, and become a stale failure when the TTL ends.
CHEAP_MAX_TTL = 5.0


@dataclass(frozen=True)
class CheckResult:
    code: str
    ok: bool
    detail: str = ""


class Preflight:
    def __init__(self, checks: list[tuple[str, CheckFn, float]], clock=time.monotonic):
        """checks: (code, fn, ttl_sec); ttl 0 = evaluate every call (cheap checks)."""
        self.checks, self.clock = checks, clock
        self._cache: dict[str, tuple[float, CheckResult]] = {}
        self._lock = threading.Lock()

    def run(self, force: bool = False) -> list[CheckResult]:
        out = []
        now = self.clock()
        for code, fn, ttl in self.checks:
            with self._lock:
                cached = self._cache.get(code)
            if cached and not force and ttl and now - cached[0] < ttl:
                out.append(cached[1])
                continue
            try:
                ok, detail = fn()
            except Exception as exc:
                ok, detail = False, repr(exc)
            res = CheckResult(code, bool(ok), str(detail)[:200])
            with self._lock:
                self._cache[code] = (now, res)
            out.append(res)
        return out

    def cached(self) -> list[CheckResult]:
        """Last known results. An expired TTL is a failure and does not re-run the check."""
        now = self.clock()
        out = []
        with self._lock:
            for code, _, ttl in self.checks:
                cached = self._cache.get(code)
                if cached is None:
                    out.append(CheckResult(code, False, "not checked yet"))
                elif ttl and now - cached[0] >= ttl:
                    out.append(CheckResult(code, False, "stale"))
                else:
                    out.append(cached[1])
        return out

    def refresh_for_observation(self) -> list[CheckResult]:
        """Refresh cheap checks. Expensive ones are reported from cache or as stale."""
        out = []
        now = self.clock()
        for code, fn, ttl in self.checks:
            with self._lock:
                cached = self._cache.get(code)
            if ttl > CHEAP_MAX_TTL:
                if cached is None:
                    out.append(CheckResult(code, False, "not checked yet"))
                elif now - cached[0] < ttl:
                    out.append(cached[1])
                else:
                    out.append(CheckResult(code, False, "stale"))
                continue
            if cached and ttl and now - cached[0] < ttl:
                out.append(cached[1])
                continue
            try:
                ok, detail = fn()
            except Exception as exc:
                ok, detail = False, repr(exc)
            res = CheckResult(code, bool(ok), str(detail)[:200])
            with self._lock:
                self._cache[code] = (now, res)
            out.append(res)
        return out

    @staticmethod
    def summary(results: list[CheckResult]) -> tuple[bool, tuple[str, ...]]:
        failures = tuple(f"{r.code}: {r.detail}" if r.detail else r.code for r in results if not r.ok)
        return not failures, failures


# ----- concrete checks (Windows farm PC) ---------------------------------------------

def check_worker_installed() -> tuple[bool, str]:
    from modules.combat import csgobot_ai
    if not csgobot_ai.is_installed():
        return False, "vendor/csgobot not installed"
    if csgobot_ai.python_executable() is None:
        return False, "csgobot venv python missing"
    return True, ""


def check_worker_preflight() -> tuple[bool, str]:
    from modules.combat import csgobot_ai
    script = csgobot_ai._csgobot_dir() / "tools" / "preflight.py"
    if not script.is_file():
        return False, "tools/preflight.py missing"
    ok, msgs = csgobot_ai.check_csgobot_preflight()
    return ok, "; ".join(msgs[:2])


def check_virtual_camera() -> tuple[bool, str]:
    from modules.combat import csgobot_ai
    return csgobot_ai.check_obs_virtual_camera()


def check_inferno_pack() -> tuple[bool, str]:
    from modules.combat import csgobot_ai
    script = csgobot_ai._csgobot_dir() / "tools" / "nav_preflight.py"
    if not script.is_file():
        return False, "tools/nav_preflight.py missing"
    ok, info = csgobot_ai.check_nav_preflight("inferno_visual")
    err = info.get("errors") or info.get("error") or ""
    return ok, "; ".join(map(str, err[:2])) if isinstance(err, list) else str(err)


def check_cs2_client_size(find_hwnd: Callable[[], int] | None = None) -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "Windows only"
    from modules.ui_nav.window import client_size, find_cs2_hwnd
    hwnd = (find_hwnd or find_cs2_hwnd)()
    if not hwnd:
        return False, "CS2 window not found"
    size = client_size(hwnd)
    return tuple(size) == REQUIRED_CLIENT, f"{size[0]}x{size[1]} (нужно 1280x720)"


def check_file_fresh(path: Callable[[], Path | None], max_age_sec: float, what: str) -> CheckFn:
    def fn() -> tuple[bool, str]:
        p = path()
        if p is None or not p.is_file():
            return False, f"{what}: нет файла"
        age = time.time() - p.stat().st_mtime
        return age <= max_age_sec, f"{what}: {age:.0f}s"
    return fn
