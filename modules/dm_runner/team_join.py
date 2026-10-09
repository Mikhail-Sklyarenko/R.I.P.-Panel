"""DM team-pick: click СЛУЧАЙНЫЙ ВЫБОР until overlay clears."""

from __future__ import annotations

import time
from typing import Callable, Protocol

from modules.ui_nav.coords import NavCoords
from modules.ui_nav.detectors import ScreenState, detect_probe_key, detect_state
from modules.ui_nav.errors import UiNavTimeoutError

_CLEAR_STREAK_REQUIRED = 3


class _TeamDriver(Protocol):
    def capture(self): ...

    def click(self, point) -> None: ...


def past_team_select_screen(img, coords: NavCoords) -> bool:
    """True when team overlay is gone and player is on map (strict HUD or invuln)."""
    if coords.base_width==1280:
        from modules.ui_nav.menu_labels import play_button
        if play_button(img) is not None:return False
    if detect_probe_key(img, coords, "team_select", min_match=1):
        return False
    if detect_probe_key(img, coords, "spawn_invuln", min_match=2):
        return True
    probe_count = len(coords.probes("in_dm")) or 1
    return detect_state(img, ScreenState.IN_DM, coords, min_match=probe_count)


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
    on_team_random_clicked: Callable[[], None] | None = None,
) -> int:
    """Act only on stable team UI; the legacy callback runs AFTER spawn confirmation."""
    deadline = time.monotonic() + max(5.0, timeout_sec)
    last_click = float('-inf')
    clicks = 0
    clear_streak = team_streak = 0
    while time.monotonic() < deadline:
        if should_stop and should_stop():
            raise UiNavTimeoutError('team select: stopped')
        img = driver.capture()
        if past_team_select_screen(img, coords):
            clear_streak += 1
            team_streak = 0
            if clear_streak >= _CLEAR_STREAK_REQUIRED:
                if on_progress:on_progress('dm nav: spawn HUD confirmed')
                if on_team_random_clicked:on_team_random_clicked()
                return clicks
        else:
            clear_streak = 0
            team_visible = detect_probe_key(img, coords, 'team_select')
            team_streak = team_streak + 1 if team_visible else 0
            now = time.monotonic()
            if team_streak >= 3 and now-last_click >= max(1.,click_retry_sec):
                _click_team_random(driver,coords,on_progress=on_progress,
                    log_step=log_step,attempt=clicks+1,team_visible=True)
                clicks += 1
                last_click = now
                team_streak = 0
        time.sleep(.25)
    raise UiNavTimeoutError(f'timeout waiting for confirmed spawn ({timeout_sec:.0f}s); clicks={clicks}')
