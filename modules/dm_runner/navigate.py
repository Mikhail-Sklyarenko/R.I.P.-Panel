"""Solo Deathmatch navigation (не Wingman fsm.cfg)."""

from __future__ import annotations

import sys
import time
from typing import Callable, Protocol

from config.schema import AppConfig
from core.events import EventType
from modules.ui_nav.artifacts import ArtifactStore
from modules.ui_nav.coords import load_nav_coords_for_hwnd
from modules.ui_nav.detectors import ScreenState, detect_state, wait_for_state
from modules.ui_nav.driver import NavDriver, SimDriver, create_driver
from modules.dm_runner.errors import DmNavStopped
from modules.ui_nav.errors import UiNavError, UiNavTimeoutError


class _Emit(Protocol):
    def __call__(
        self,
        event: EventType,
        detail: str = "",
        *,
        drop_log: bool = False,
    ) -> None: ...


class DmNavigator:
    def __init__(
        self,
        *,
        config: AppConfig,
        session_id: str,
        login: str,
        emit: _Emit | None = None,
        hwnd: int | None = None,
        on_nav_progress: Callable[[str], None] | None = None,
        menu_probe_warn: bool = False,
        menu_confirmed: bool = False,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self.config = config
        self.session_id = session_id
        self.login = login
        self.emit = emit
        self.hwnd = hwnd
        self.on_nav_progress = on_nav_progress
        self.menu_probe_warn = menu_probe_warn
        self.menu_confirmed = menu_confirmed
        self.should_stop = should_stop
        self._menu_nav_done = False
        self.coords = load_nav_coords_for_hwnd(
            hwnd,
            config.cs_resolution,
            on_warn=self._nav_progress,
        )
        self.artifacts = ArtifactStore(session_id)
        self.artifacts.save_json(
            "meta",
            {
                "login": login,
                "resolution": config.cs_resolution,
                "hwnd": hwnd,
                "game_search_timeout_sec": config.game_search_timeout_sec,
                "map_load_delay_sec": config.map_load_delay_sec,
            },
        )
        self.driver = create_driver(
            self.coords,
            self.artifacts,
            hwnd=hwnd,
        )

    def _nav_progress(self, msg: str) -> None:
        if self.on_nav_progress:
            self.on_nav_progress(msg)

    def _abort_if_stopped(self) -> None:
        if self.should_stop and self.should_stop():
            raise DmNavStopped("dm nav: stopped by operator")
        if (
            self.hwnd
            and not isinstance(self.driver, SimDriver)
            and sys.platform == "win32"
        ):
            from modules.ui_nav.window import is_valid_hwnd

            if not is_valid_hwnd(self.hwnd):
                raise DmNavStopped("dm nav: stopped or window closed")

    def _set_sim_phase(self, state: ScreenState) -> None:
        if isinstance(self.driver, SimDriver):
            self.driver.set_phase(
                {
                    ScreenState.MAIN_MENU: "main_menu",
                    ScreenState.SEARCHING: "searching",
                    ScreenState.IN_DM: "in_dm",
                }[state]
            )

    def _e(self, event: EventType, detail: str) -> None:
        if self.emit:
            self.emit(event, detail)

    def _prepare_cs2_window(self) -> None:
        if isinstance(self.driver, SimDriver):
            return
        try:
            from modules.utils.windows import move_all_cs_windows

            result = move_all_cs_windows(config=self.config)
            if result.count:
                self._nav_progress(
                    f"dm layout: {result.count} CS window(s) → {result.width}x{result.height}"
                )
                if self.hwnd:
                    self.coords = load_nav_coords_for_hwnd(
                        self.hwnd,
                        self.config.cs_resolution,
                        on_warn=self._nav_progress,
                    )
                if not isinstance(self.driver, SimDriver):
                    time.sleep(0.5)
        except Exception as exc:
            self._nav_progress(f"dm layout skipped: {exc}")

    def wait_main_menu(
        self,
        timeout: float | None = None,
        *,
        min_match: int | None = None,
    ) -> None:
        self._set_sim_phase(ScreenState.MAIN_MENU)
        if timeout is None:
            timeout = float(self.config.cs2_main_menu_wait_timeout_sec)
        if min_match is None:
            min_match = len(self.coords.probes("main_menu"))
        wait_for_state(
            self.driver,
            ScreenState.MAIN_MENU,
            self.coords,
            self.artifacts,
            timeout_sec=timeout,
            min_match=min_match,
        )

    def _pre_click_main_menu_wait(self) -> bool:
        """Wait for main_menu probes. Returns True if main_menu_play already clicked."""
        menu_timeout = float(max(15, int(self.config.cs2_main_menu_wait_timeout_sec)))
        strict_count = len(self.coords.probes("main_menu"))
        if self.menu_confirmed:
            self._nav_progress(
                "dm nav: launcher confirmed main menu (strict); waiting before clicks"
            )
            min_match = strict_count
        else:
            if self.menu_probe_warn:
                self._nav_progress(
                    "dm nav: main menu was not confirmed at launch; soft probe wait"
                )
            min_match = 1
        try:
            self.wait_main_menu(timeout=menu_timeout, min_match=min_match)
            return False
        except UiNavTimeoutError:
            img = self.driver.capture()
            if detect_state(
                img, ScreenState.MAIN_MENU, self.coords, min_match=1
            ) and not detect_state(
                img, ScreenState.MAIN_MENU, self.coords, min_match=strict_count
            ):
                self._nav_progress("dm nav: soft main_menu on frame; proceeding")
                return False
            pt = self.coords.click("main_menu_play")
            self._nav_progress(
                f"dm nav: main_menu probe timeout; controlled click ИГРАТЬ @({pt.x},{pt.y})"
            )
            self._click_target("main_menu_play")
            return True

    def _click_sequence_after_play(self) -> None:
        for name in ("mode_deathmatch", "start_search"):
            self._click_target(name)
            time.sleep(0.35)

    def _run_menu_and_clicks(self) -> None:
        """Menu wait + click sequence (once per session)."""
        if self._menu_nav_done:
            return
        play_clicked = self._pre_click_main_menu_wait()
        self._abort_if_stopped()
        self._e(EventType.IN_MENU, "dm_runner: main menu")

        if play_clicked:
            self._click_sequence_after_play()
        else:
            self.click_sequence_deathmatch()
        self._menu_nav_done = True

    def _confirm_search_started(self) -> None:
        """Emit searching_dm only after searching probes match (or fast in_dm load)."""
        self._set_sim_phase(ScreenState.SEARCHING)
        search_timeout = float(self.config.game_search_timeout_sec)

        try:
            wait_for_state(
                self.driver,
                ScreenState.SEARCHING,
                self.coords,
                self.artifacts,
                timeout_sec=search_timeout,
            )
            self._e(EventType.SEARCHING_DM, "dm_runner: search started")
            return
        except UiNavTimeoutError:
            img = self.driver.capture()
            if detect_state(img, ScreenState.IN_DM, self.coords):
                self._nav_progress(
                    "dm nav: searching screen skipped; in_dm probes already match"
                )
                self._e(
                    EventType.SEARCHING_DM,
                    "dm_runner: search started (fast load, searching screen skipped)",
                )
                return
            if detect_state(img, ScreenState.MAIN_MENU, self.coords):
                self._nav_progress(
                    "dm nav: still on main_menu after start_search; click likely missed"
                )
            else:
                self._nav_progress(
                    "dm nav: searching not confirmed after clicks; match search likely not started"
                )
            self.artifacts.log_step(
                "search_not_confirmed",
                timeout_sec=search_timeout,
            )
            raise UiNavTimeoutError(
                f"timeout waiting for searching ({search_timeout}s); "
                "start_search not confirmed"
            ) from None

    def _wait_search_and_in_dm(self) -> None:
        self._confirm_search_started()

        self._set_sim_phase(ScreenState.IN_DM)
        wait_for_state(
            self.driver,
            ScreenState.IN_DM,
            self.coords,
            self.artifacts,
            timeout_sec=float(self.config.map_load_delay_sec),
        )
        self._e(EventType.IN_DM, "dm_runner: in_dm")

    def _click_target(self, name: str) -> None:
        before = self.driver.capture()
        on_main_before = detect_state(before, ScreenState.MAIN_MENU, self.coords)
        last_err: Exception | None = None
        for attempt in range(1, 3):
            pt = self.coords.click(name)
            self._nav_progress(f"dm click {name} @({pt.x},{pt.y})")
            try:
                self.driver.click(pt)
            except UiNavError as exc:
                last_err = exc
                time.sleep(0.3)
                continue
            time.sleep(0.55)
            after = self.driver.capture()
            self.artifacts.save_image(f"after_click_{name}_{attempt}", after)
            self.artifacts.log_step(
                "click",
                target=name,
                x=pt.x,
                y=pt.y,
                attempt=attempt,
            )
            if name == "main_menu_play" and on_main_before and not self.driver.sim:
                if not detect_state(after, ScreenState.MAIN_MENU, self.coords):
                    return
                if attempt < 2:
                    continue
                raise UiNavError(f"click {name} did not leave main menu")
            return
        if last_err:
            raise last_err
        raise UiNavError(f"click {name} failed")

    def click_sequence_deathmatch(self) -> None:
        for name in ("main_menu_play", "mode_deathmatch", "start_search"):
            self._click_target(name)
            time.sleep(0.35)

    def navigate_to_dm(self) -> None:
        """Меню → поиск DM → in_dm (таймауты из config)."""
        self._abort_if_stopped()
        self._run_menu_and_clicks()
        self._wait_search_and_in_dm()

    def _retry_focus_once(self) -> None:
        if isinstance(self.driver, SimDriver) or not self.hwnd:
            return
        from modules.ui_nav.actions import focus_window

        try:
            focus_window(self.hwnd)
        except UiNavError as exc:
            self._nav_progress(f"dm nav: focus retry failed ({exc})")

    def navigate_to_dm_with_retries(self) -> None:
        self._prepare_cs2_window()
        last_err: Exception | None = None
        for attempt in range(1, self.config.search_retries + 1):
            try:
                self._abort_if_stopped()
                self.artifacts.log_step("dm_attempt", attempt=attempt)
                if self._menu_nav_done:
                    self._nav_progress(
                        f"dm nav: retry in_dm wait (attempt {attempt})"
                    )
                    self._wait_search_and_in_dm()
                else:
                    self.navigate_to_dm()
                return
            except DmNavStopped:
                raise
            except (UiNavTimeoutError, UiNavError) as exc:
                last_err = exc
                self.artifacts.log_step("dm_attempt_failed", attempt=attempt, err=str(exc))
                if "focus" in str(exc).lower() or "SetForegroundWindow" in str(exc):
                    self._retry_focus_once()
                if attempt < self.config.search_retries:
                    time.sleep(2.0)
                    if not self._menu_nav_done:
                        self._set_sim_phase(ScreenState.MAIN_MENU)
        if last_err:
            raise last_err

    def disconnect(self) -> None:
        """Выход из DM (bind j disconnect в resources/cs2/fsm.cfg)."""
        self.driver.press("j")
        self.artifacts.log_step("disconnect_key", key="j")
        time.sleep(1.0)
        self._set_sim_phase(ScreenState.MAIN_MENU)
        try:
            wait_for_state(
                self.driver,
                ScreenState.MAIN_MENU,
                self.coords,
                self.artifacts,
                timeout_sec=20.0,
            )
        except UiNavTimeoutError:
            pt = self.coords.click("leave_match")
            self._nav_progress(f"dm click leave_match @({pt.x},{pt.y})")
            self.driver.click(pt)
            self.artifacts.log_step("disconnect_click", target="leave_match")
        self._e(EventType.EXITED, "dm_runner: disconnected")

    def run_in_dm_cycles(self, cycles: int = 5) -> int:
        """
        Критерий B5: cycles раз in_dm без ручных кликов.
        Возвращает число успешных циклов.
        """
        ok = 0
        for n in range(1, cycles + 1):
            self.artifacts.log_step("cycle_start", n=n, of=cycles)
            try:
                self.navigate_to_dm_with_retries()
                ok += 1
                self.artifacts.log_step("cycle_in_dm_ok", n=n)
                if n < cycles:
                    self.disconnect()
            except (UiNavTimeoutError, UiNavError) as exc:
                self.artifacts.log_step("cycle_failed", n=n, err=str(exc))
                break
        self.artifacts.save_json("cycles_result", {"requested": cycles, "ok": ok})
        return ok
