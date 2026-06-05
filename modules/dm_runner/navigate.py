"""Solo Deathmatch navigation (не Wingman fsm.cfg)."""

from __future__ import annotations

import time
from typing import Callable, Protocol

from config.schema import AppConfig
from core.events import EventType
from modules.ui_nav.artifacts import ArtifactStore
from modules.ui_nav.coords import load_nav_coords
from modules.ui_nav.detectors import ScreenState, wait_for_state
from modules.ui_nav.driver import NavDriver, SimDriver, create_driver
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
    ) -> None:
        self.config = config
        self.session_id = session_id
        self.login = login
        self.emit = emit
        self.coords = load_nav_coords(config.cs_resolution)
        self.artifacts = ArtifactStore(session_id)
        self.artifacts.save_json(
            "meta",
            {
                "login": login,
                "resolution": config.cs_resolution,
                "game_search_timeout_sec": config.game_search_timeout_sec,
                "map_load_delay_sec": config.map_load_delay_sec,
            },
        )
        self.driver = create_driver(self.coords, self.artifacts, hwnd=hwnd)

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

    def wait_main_menu(self, timeout: float = 30.0) -> None:
        self._set_sim_phase(ScreenState.MAIN_MENU)
        wait_for_state(
            self.driver,
            ScreenState.MAIN_MENU,
            self.coords,
            self.artifacts,
            timeout_sec=timeout,
        )

    def click_sequence_deathmatch(self) -> None:
        for name in ("main_menu_play", "mode_deathmatch", "start_search"):
            pt = self.coords.click(name)
            self.driver.click(pt)
            self.artifacts.log_step("click", target=name, x=pt.x, y=pt.y)

    def navigate_to_dm(self) -> None:
        """Меню → поиск DM → in_dm (таймауты из config)."""
        self.wait_main_menu(timeout=45.0)
        self._e(EventType.IN_MENU, "dm_runner: main menu")

        self.click_sequence_deathmatch()
        self._set_sim_phase(ScreenState.SEARCHING)
        self._e(EventType.SEARCHING_DM, "dm_runner: search started")

        try:
            wait_for_state(
                self.driver,
                ScreenState.SEARCHING,
                self.coords,
                self.artifacts,
                timeout_sec=min(15.0, self.config.game_search_timeout_sec),
            )
        except UiNavTimeoutError:
            self.artifacts.log_step("searching_skip", detail="probe optional")

        self._set_sim_phase(ScreenState.IN_DM)
        wait_for_state(
            self.driver,
            ScreenState.IN_DM,
            self.coords,
            self.artifacts,
            timeout_sec=float(self.config.map_load_delay_sec),
        )
        self._e(EventType.IN_DM, "dm_runner: in_dm")

    def navigate_to_dm_with_retries(self) -> None:
        last_err: Exception | None = None
        for attempt in range(1, self.config.search_retries + 1):
            try:
                self.artifacts.log_step("dm_attempt", attempt=attempt)
                self.navigate_to_dm()
                return
            except (UiNavTimeoutError, UiNavError) as exc:
                last_err = exc
                self.artifacts.log_step("dm_attempt_failed", attempt=attempt, err=str(exc))
                if attempt < self.config.search_retries:
                    time.sleep(2.0)
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
