"""Детекторы экрана по color probes (solo DM UI)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from PIL import Image

from modules.ui_nav.artifacts import ArtifactStore
from modules.ui_nav.coords import ColorProbe, NavCoords
from modules.ui_nav.errors import UiNavTimeoutError
from modules.ui_nav.driver import NavDriver


class ScreenState(str, Enum):
    MAIN_MENU = "main_menu"
    SEARCHING = "searching"
    IN_DM = "in_dm"


_STATE_MAP = {
    ScreenState.MAIN_MENU: "main_menu",
    ScreenState.SEARCHING: "searching",
    ScreenState.IN_DM: "in_dm",
}

_STRICT_STATES = frozenset({ScreenState.MAIN_MENU, ScreenState.IN_DM})


@dataclass(frozen=True)
class ProbeMatchResult:
    matched: bool
    x: int
    y: int
    actual_rgb: tuple[int, int, int]
    expected_rgb: tuple[int, int, int]


@dataclass(frozen=True)
class InDmWaitResult:
    """strict_ok: all in_dm probes matched. soft_peek: ≥1 probe × N polls."""

    strict_ok: bool
    soft_peek: bool = False
    timed_out: bool = False
    attempts: int = 0

    @property
    def ok(self) -> bool:
        return self.strict_ok or self.soft_peek


def _probe_pixel(img: Image.Image, probe: ColorProbe) -> tuple[int, int, int] | None:
    x, y = probe.x, probe.y
    if x >= img.width or y >= img.height:
        return None
    return img.getpixel((x, y))[:3]


def _probe_match(img: Image.Image, probe: ColorProbe) -> bool:
    px = _probe_pixel(img, probe)
    if px is None:
        return False
    r, g, b = px
    tr, tg, tb = probe.rgb
    tol = probe.tolerance
    return (
        abs(r - tr) <= tol and abs(g - tg) <= tol and abs(b - tb) <= tol
    )


def probe_match_results(
    img: Image.Image,
    state: ScreenState,
    coords: NavCoords,
) -> list[ProbeMatchResult]:
    key = _STATE_MAP[state]
    out: list[ProbeMatchResult] = []
    for probe in coords.probes(key):
        px = _probe_pixel(img, probe)
        actual = px if px is not None else (0, 0, 0)
        out.append(
            ProbeMatchResult(
                matched=_probe_match(img, probe) if px is not None else False,
                x=probe.x,
                y=probe.y,
                actual_rgb=actual,
                expected_rgb=probe.rgb,
            )
        )
    return out


def _required_matches(state: ScreenState, probe_count: int, min_match: int | None) -> int:
    if probe_count <= 0:
        return 1
    if min_match is not None:
        return min(max(1, min_match), probe_count)
    if state in _STRICT_STATES:
        return probe_count
    return max(1, probe_count - 1)


def detect_probe_key(
    img: Image.Image,
    coords: NavCoords,
    key: str,
    *,
    min_match: int | None = None,
) -> bool:
    """Match YAML detectors.<key> probes (e.g. team_select)."""
    probes = coords.probes(key)
    if not probes:
        return False
    matched = sum(1 for p in probes if _probe_match(img, p))
    required = min_match if min_match is not None else len(probes)
    return matched >= min(max(1, required), len(probes))


def detect_state(
    img: Image.Image,
    state: ScreenState,
    coords: NavCoords,
    *,
    min_match: int | None = None,
) -> bool:
    key = _STATE_MAP[state]
    probes = coords.probes(key)
    if not probes:
        return False
    matched = sum(1 for p in probes if _probe_match(img, p))
    required = _required_matches(state, len(probes), min_match)
    return matched >= required


def wait_for_state(
    driver: NavDriver,
    state: ScreenState,
    coords: NavCoords,
    artifacts: ArtifactStore,
    *,
    timeout_sec: float,
    poll_sec: float = 0.5,
    min_match: int | None = None,
) -> Image.Image:
    deadline = time.monotonic() + timeout_sec
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        img = driver.capture()
        artifacts.save_image(f"wait_{state.value}_{attempt}", img)
        if detect_state(img, state, coords, min_match=min_match):
            artifacts.log_step("detect_ok", state=state.value, attempt=attempt)
            return img
        time.sleep(poll_sec)
    artifacts.log_step("detect_timeout", state=state.value, timeout_sec=timeout_sec)
    raise UiNavTimeoutError(f"timeout waiting for {state.value} ({timeout_sec}s)")


def wait_for_in_dm(
    driver: NavDriver,
    coords: NavCoords,
    artifacts: ArtifactStore,
    *,
    timeout_sec: float,
    poll_sec: float = 0.5,
    strict_min_match: int | None = None,
    soft_min_match: int = 1,
    soft_peek_polls: int = 3,
    on_progress: Callable[[str], None] | None = None,
    on_poll: Callable[[Image.Image], None] | None = None,
) -> InDmWaitResult:
    """
    Poll until in_dm probes match (strict all probes, or soft ≥1 probe × N polls).
    Raises UiNavTimeoutError on timeout (after progress log with probe RGB).
    """
    probe_count = len(coords.probes("in_dm"))
    strict_required = (
        strict_min_match if strict_min_match is not None else (probe_count or 1)
    )
    soft_required = min(max(1, soft_min_match), probe_count) if probe_count else 1
    deadline = time.monotonic() + timeout_sec
    attempt = 0
    last_probe_results: list[ProbeMatchResult] = []
    consecutive_soft = 0

    while time.monotonic() < deadline:
        attempt += 1
        img = driver.capture()
        if on_poll is not None:
            on_poll(img)
        artifacts.save_image(f"wait_in_dm_{attempt}", img)
        probe_results = probe_match_results(img, ScreenState.IN_DM, coords)
        last_probe_results = probe_results
        soft_hit = sum(1 for r in probe_results if r.matched) >= soft_required
        if detect_probe_key(img, coords, "team_select", min_match=1):
            soft_hit = False
        if soft_hit:
            consecutive_soft += 1
        else:
            consecutive_soft = 0
        strict = detect_state(
            img,
            ScreenState.IN_DM,
            coords,
            min_match=strict_required,
        )
        probe_kwargs: dict = {
            "attempt": attempt,
            "matched": int(soft_hit),
            "strict": int(strict),
            "img_w": img.width,
            "img_h": img.height,
        }
        for idx, result in enumerate(probe_results[:2]):
            probe_kwargs[f"p{idx}"] = int(result.matched)
            probe_kwargs[f"rgb{idx}"] = list(result.actual_rgb)
            probe_kwargs[f"exp{idx}"] = list(result.expected_rgb)
        artifacts.log_step("in_dm_probe", **probe_kwargs)
        if strict:
            artifacts.log_step("in_dm_detect_ok", attempt=attempt, strict=True)
            return InDmWaitResult(strict_ok=True, attempts=attempt)
        if soft_hit and consecutive_soft >= max(1, soft_peek_polls):
            artifacts.log_step(
                "in_dm_soft_peek_ok",
                attempt=attempt,
                consecutive=consecutive_soft,
            )
            if on_progress:
                on_progress(
                    f"in_dm soft_peek confirmed after {consecutive_soft} polls"
                )
            return InDmWaitResult(
                strict_ok=False,
                soft_peek=True,
                attempts=attempt,
            )
        time.sleep(poll_sec)

    artifacts.log_step(
        "in_dm_detect_timeout",
        timeout_sec=timeout_sec,
        attempts=attempt,
    )
    if on_progress and last_probe_results:
        r0 = last_probe_results[0]
        p1 = int(last_probe_results[1].matched) if len(last_probe_results) > 1 else 0
        on_progress(
            "in_dm timeout: "
            f"p0={int(r0.matched)} p1={p1} "
            f"last@({r0.x},{r0.y})={list(r0.actual_rgb)} "
            f"expected={list(r0.expected_rgb)}"
        )
    raise UiNavTimeoutError(f"timeout waiting for in_dm ({timeout_sec}s)")
