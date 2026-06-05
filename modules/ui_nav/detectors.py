"""Детекторы экрана по color probes (solo DM UI)."""

from __future__ import annotations

import time
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


def _probe_match(img: Image.Image, probe: ColorProbe) -> bool:
    x, y = probe.x, probe.y
    if x >= img.width or y >= img.height:
        return False
    r, g, b = img.getpixel((x, y))[:3]
    tr, tg, tb = probe.rgb
    tol = probe.tolerance
    return (
        abs(r - tr) <= tol and abs(g - tg) <= tol and abs(b - tb) <= tol
    )


def detect_state(img: Image.Image, state: ScreenState, coords: NavCoords) -> bool:
    key = _STATE_MAP[state]
    probes = coords.probes(key)
    if not probes:
        return False
    matched = sum(1 for p in probes if _probe_match(img, p))
    return matched >= max(1, len(probes) - 1)


def wait_for_state(
    driver: NavDriver,
    state: ScreenState,
    coords: NavCoords,
    artifacts: ArtifactStore,
    *,
    timeout_sec: float,
    poll_sec: float = 0.5,
) -> Image.Image:
    deadline = time.monotonic() + timeout_sec
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        img = driver.capture()
        artifacts.save_image(f"wait_{state.value}_{attempt}", img)
        if detect_state(img, state, coords):
            artifacts.log_step("detect_ok", state=state.value, attempt=attempt)
            return img
        time.sleep(poll_sec)
    artifacts.log_step("detect_timeout", state=state.value, timeout_sec=timeout_sec)
    raise UiNavTimeoutError(f"timeout waiting for {state.value} ({timeout_sec}s)")
