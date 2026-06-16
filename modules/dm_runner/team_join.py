"""DM team-pick: click СЛУЧАЙНЫЙ ВЫБОР until overlay clears."""

from __future__ import annotations

import time
from typing import Callable, Protocol

from modules.ui_nav.coords import NavCoords
from modules.ui_nav.detectors import detect_probe_key
from modules.ui_nav.errors import UiNavTimeoutError

_BLIND_CLICKS_MAX = 8


class _TeamDriver(Protocol):
    def capture(self): ...

    def click(self, point) -> None: ...


def wait_team_select_done(
    driver: _TeamDriver,
    coords: NavCoords,
    *,
    timeout_sec: float = 45.0,
    click_retry_sec: float = 2.0,
    on_progress: Callable[[str], None] | None = None,
    log_step: Callable[..., None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    """
    Click team_random while team_select visible; return when overlay gone.

    Uses min_match=1 on team_select probes (header OR button) for RU UI drift.
    If probes miss the overlay, still clicks team_random up to _BLIND_CLICKS_MAX.
    """
    deadline = time.monotonic() + max(5.0, timeout_sec)
    last_click = 0.0
    clicks = 0
    saw_team = False
    clear_streak = 0

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    while time.monotonic() < deadline:
        if should_stop and should_stop():
            raise UiNavTimeoutError("team select: stopped")
        img = driver.capture()
        team_visible = detect_probe_key(img, coords, "team_select", min_match=1)
        if team_visible:
            saw_team = True
            clear_streak = 0
        else:
            clear_streak += 1

        now = time.monotonic()
        need_click = team_visible or clicks < _BLIND_CLICKS_MAX
        if need_click and now - last_click >= click_retry_sec:
            try:
                pt = coords.click("team_random")
            except KeyError as exc:
                raise UiNavTimeoutError(
                    "team_random missing in coords profile — set cs_resolution"
                ) from exc

            mode = "team overlay" if team_visible else "blind (probe miss)"
            progress(f"dm nav: team select → random @({pt.x},{pt.y}) [{mode}]")
            driver.click(pt)
            if log_step:
                log_step(
                    "team_random_click",
                    x=pt.x,
                    y=pt.y,
                    attempt=clicks + 1,
                    team_visible=team_visible,
                )
            last_click = now
            clicks += 1
            time.sleep(0.5)

        if clicks > 0 and clear_streak >= 2:
            if saw_team:
                progress("dm nav: team select cleared")
            elif clicks >= _BLIND_CLICKS_MAX:
                progress("dm nav: team select blind clicks done (probe never matched)")
            return clicks

        time.sleep(0.3)

    raise UiNavTimeoutError(
        f"timeout on team select screen ({timeout_sec:.0f}s); clicks={clicks}"
    )
