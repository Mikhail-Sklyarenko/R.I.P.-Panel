"""DM team-pick: click СЛУЧАЙНЫЙ ВЫБОР until overlay clears."""

from __future__ import annotations

import time
from typing import Callable, Protocol

from modules.ui_nav.coords import NavCoords
from modules.ui_nav.detectors import ScreenState, detect_probe_key, detect_state
from modules.ui_nav.errors import UiNavTimeoutError

# Cap blind LMB clicks — each click is +attack when team overlay is already gone.
_MAX_BLIND_CLICKS = 3


class _TeamDriver(Protocol):
    def capture(self): ...

    def click(self, point) -> None: ...


def past_team_select_screen(img, coords: NavCoords) -> bool:
    """True when team overlay is gone and in_dm HUD is visible."""
    if detect_probe_key(img, coords, "team_select", min_match=2):
        return False
    return detect_state(img, ScreenState.IN_DM, coords)


def _click_team_random(
    driver: _TeamDriver,
    coords: NavCoords,
    *,
    on_progress: Callable[[str], None] | None,
    log_step: Callable[..., None] | None,
    attempt: int,
    team_visible: bool,
) -> None:
    try:
        pt = coords.click("team_random")
    except KeyError as exc:
        raise UiNavTimeoutError(
            "team_random missing in coords profile — set cs_resolution"
        ) from exc

    mode = "team overlay" if team_visible else "blind (probe miss)"
    if on_progress:
        on_progress(f"dm nav: team select → random @({pt.x},{pt.y}) [{mode}]")
    driver.click(pt)
    if log_step:
        log_step(
            "team_random_click",
            x=pt.x,
            y=pt.y,
            attempt=attempt,
            team_visible=team_visible,
        )


def wait_team_select_done(
    driver: _TeamDriver,
    coords: NavCoords,
    *,
    timeout_sec: float = 45.0,
    click_retry_sec: float = 1.0,
    on_progress: Callable[[str], None] | None = None,
    log_step: Callable[..., None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    """
    Click team_random while team_select visible; return when overlay gone.

    Blind clicks are capped: LMB in-game fires the weapon. If color probes miss,
    exit after clear_streak or when spawn HUD / invuln panel is detected.
    """
    deadline = time.monotonic() + max(5.0, timeout_sec)
    last_click = 0.0
    clicks = 0
    saw_team = False
    clear_streak = 0

    # Immediate click when team screen often appears right after accept.
    try:
        _click_team_random(
            driver,
            coords,
            on_progress=on_progress,
            log_step=log_step,
            attempt=1,
            team_visible=False,
        )
        clicks = 1
        last_click = time.monotonic()
        time.sleep(0.4)
    except UiNavTimeoutError:
        raise

    while time.monotonic() < deadline:
        if should_stop and should_stop():
            raise UiNavTimeoutError("team select: stopped")
        img = driver.capture()

        if past_team_select_screen(img, coords):
            if on_progress:
                on_progress("dm nav: team select cleared (in_dm HUD)")
            return clicks

        team_visible = detect_probe_key(img, coords, "team_select", min_match=2)
        if team_visible:
            saw_team = True
            clear_streak = 0
        else:
            clear_streak += 1

        if clear_streak >= 2 and clicks >= 1:
            if on_progress:
                on_progress("dm nav: team select cleared")
            return clicks

        now = time.monotonic()
        if now - last_click >= click_retry_sec:
            if team_visible or clicks < _MAX_BLIND_CLICKS:
                _click_team_random(
                    driver,
                    coords,
                    on_progress=on_progress,
                    log_step=log_step,
                    attempt=clicks + 1,
                    team_visible=team_visible,
                )
                last_click = now
                clicks += 1
                time.sleep(0.35)

        time.sleep(0.25)

    raise UiNavTimeoutError(
        f"timeout on team select screen ({timeout_sec:.0f}s); clicks={clicks}"
    )
