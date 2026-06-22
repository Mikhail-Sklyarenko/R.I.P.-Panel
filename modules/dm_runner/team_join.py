"""DM team-pick: click СЛУЧАЙНЫЙ ВЫБОР until overlay clears."""

from __future__ import annotations

import time
from typing import Callable, Protocol

from modules.ui_nav.coords import NavCoords
from modules.ui_nav.detectors import ScreenState, detect_probe_key, detect_state
from modules.ui_nav.errors import UiNavTimeoutError

_MAX_BLIND_CLICKS = 5
_TEAM_OVERLAY_WAIT_SEC = 15.0
_TEAM_OVERLAY_GRACE_SEC = 1.0
_CLEAR_STREAK_REQUIRED = 2


class _TeamDriver(Protocol):
    def capture(self): ...

    def click(self, point) -> None: ...


def past_team_select_screen(img, coords: NavCoords) -> bool:
    """True when team overlay is gone and player is on map (strict HUD or invuln)."""
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
    """
    Click team_random while overlay visible; never LMB-spam after overlay was seen.

    Waits for team overlay before blind clicks. After a confirmed overlay click,
    optional on_team_random_clicked (console autobuy). No further LMB once overlay
    was seen until spawn HUD confirms join.
    """
    deadline = time.monotonic() + max(5.0, timeout_sec)
    last_click = 0.0
    clicks = 0
    started = time.monotonic()
    saw_team_overlay = False
    console_buy_fired = False
    clear_streak = 0
    overlay_wait_logged = False

    while time.monotonic() < deadline:
        if should_stop and should_stop():
            raise UiNavTimeoutError("team select: stopped")
        img = driver.capture()

        if past_team_select_screen(img, coords):
            clear_streak += 1
            if clear_streak >= _CLEAR_STREAK_REQUIRED:
                if on_progress:
                    on_progress("dm nav: team select cleared (spawn HUD)")
                return clicks
        else:
            clear_streak = 0

        team_visible = detect_probe_key(img, coords, "team_select", min_match=1)
        if team_visible:
            saw_team_overlay = True
        elif not saw_team_overlay:
            elapsed_wait = time.monotonic() - started
            if elapsed_wait < _TEAM_OVERLAY_WAIT_SEC:
                if not overlay_wait_logged and on_progress:
                    on_progress("dm nav: waiting for team select overlay…")
                    overlay_wait_logged = True
                time.sleep(0.3)
                continue

        now = time.monotonic()
        elapsed = now - started

        may_blind = (
            not saw_team_overlay
            and not team_visible
            and clicks < _MAX_BLIND_CLICKS
            and elapsed >= _TEAM_OVERLAY_GRACE_SEC
            and now - last_click >= click_retry_sec
        )
        may_team = team_visible and (now - last_click >= click_retry_sec)

        if may_team or may_blind:
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
            time.sleep(0.4)

            if (
                team_visible
                and on_team_random_clicked
                and not console_buy_fired
            ):
                if on_progress:
                    on_progress("dm nav: autobuy console after team random")
                try:
                    on_team_random_clicked()
                except Exception as exc:
                    if on_progress:
                        on_progress(f"dm nav: autobuy console warn ({exc})")
                console_buy_fired = True

        time.sleep(0.25)

    raise UiNavTimeoutError(
        f"timeout on team select screen ({timeout_sec:.0f}s); clicks={clicks}"
    )
