"""DM team-pick: click СЛУЧАЙНЫЙ ВЫБОР until overlay clears."""

from __future__ import annotations

import time
from typing import Callable, Protocol

from modules.ui_nav.coords import NavCoords
from modules.ui_nav.detectors import detect_probe_key
from modules.ui_nav.errors import UiNavTimeoutError


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
    """
    deadline = time.monotonic() + max(5.0, timeout_sec)
    last_click = 0.0
    clicks = 0

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    while time.monotonic() < deadline:
        if should_stop and should_stop():
            raise UiNavTimeoutError("team select: stopped")
        img = driver.capture()
        if not detect_probe_key(img, coords, "team_select", min_match=1):
            if clicks:
                progress("dm nav: team select cleared")
            return clicks

        now = time.monotonic()
        if now - last_click < click_retry_sec:
            time.sleep(0.3)
            continue

        try:
            pt = coords.click("team_random")
        except KeyError as exc:
            raise UiNavTimeoutError(
                "team_random missing in coords profile — set cs_resolution"
            ) from exc

        progress(f"dm nav: team select → random @({pt.x},{pt.y})")
        driver.click(pt)
        if log_step:
            log_step("team_random_click", x=pt.x, y=pt.y, attempt=clicks + 1)
        last_click = now
        clicks += 1
        time.sleep(0.5)

    raise UiNavTimeoutError(
        f"timeout on team select screen ({timeout_sec:.0f}s); clicks={clicks}"
    )
