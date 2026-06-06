"""Детекторы экрана по color probes (solo DM UI)."""

from __future__ import annotations

import time
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
