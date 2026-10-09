"""Solo Deathmatch navigation (не Wingman fsm.cfg)."""

from __future__ import annotations

import sys
import time
from typing import Callable, Protocol

from config.schema import AppConfig
from core.events import EventType
from modules.ui_nav.artifacts import ArtifactStore
from modules.ui_nav.coords import load_nav_coords_for_hwnd
from modules.ui_nav.detectors import (
    ScreenState,
    detect_probe_key,
    detect_state,
    wait_for_state,
)
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
        on_team_joined: Callable[[], None] | None = None,
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
        self.on_team_joined = on_team_joined
        self._menu_nav_done = False
        self._search_requested = False
        self._team_done_mono: float | None = None
        self._startup_buy_done = False
        self._combat_preload_started = False
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
        if self.hwnd is None and not isinstance(self.driver,SimDriver):
            self.hwnd=self.driver.hwnd

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
            should_stop=self.should_stop,
        )

    _SOFT_MENU_WAIT_SEC = 15.0

    def _pre_click_main_menu_wait(self) -> bool:
        """Wait for main_menu probes. Returns True if main_menu_play already clicked."""
        menu_timeout = float(max(15, int(self.config.cs2_main_menu_wait_timeout_sec)))
        strict_count = len(self.coords.probes("main_menu"))
        if self.menu_confirmed:
            self._nav_progress(
                "dm nav: launcher confirmed main menu (strict); waiting before clicks"
            )
            min_match = strict_count
            wait_timeout = menu_timeout
        else:
            if self.menu_probe_warn:
                self._nav_progress(
                    "dm nav: main menu was not confirmed at launch; confirming all menu probes"
                )
                wait_timeout = min(menu_timeout, self._SOFT_MENU_WAIT_SEC)
            else:
                wait_timeout = menu_timeout
            min_match = strict_count
        from modules.ui_nav.cs2_modal_dismiss import dismiss_cs2_modals

        if self.hwnd and not isinstance(self.driver, SimDriver):
            dismiss_cs2_modals(self.hwnd, on_progress=self._nav_progress)
        try:
            self.wait_main_menu(timeout=wait_timeout, min_match=min_match)
            return False
        except UiNavTimeoutError:
            self._abort_if_stopped()
            img=self.driver.capture()
            if detect_state(img,ScreenState.MAIN_MENU,self.coords):
                return False
            raise UiNavTimeoutError('Main menu unconfirmed; no blind Play click') from None

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

        deadline=time.monotonic()+search_timeout
        stable=0
        from modules.dm_runner.team_join import past_team_select_screen
        while time.monotonic()<deadline:
            self._abort_if_stopped()
            img=self.driver.capture()
            found=(detect_state(img,ScreenState.SEARCHING,self.coords)
                   or detect_probe_key(img,self.coords,'team_select')
                   or past_team_select_screen(img,self.coords))
            stable=stable+1 if found else 0
            if stable>=3:
                self._e(EventType.SEARCHING_DM,'dm_runner: search or loaded match confirmed')
                return
            time.sleep(.25)
        raise UiNavTimeoutError('Search/load not confirmed')

    def _in_dm_detail(self, *, soft_peek: bool) -> str:
        if soft_peek:
            return "dm_runner: in_dm (soft_peek)"
        return "dm_runner: in_dm"

    def _bootstrap_cs2_farm_cfg(self) -> None:
        """Re-copy farm_panel.cfg into game/csgo/cfg (binds already from +exec at launch)."""
        if isinstance(self.driver, SimDriver):
            return
        from modules.launcher.cs2 import redeploy_farm_cfg

        try:
            path = redeploy_farm_cfg(self.config)
            self._nav_progress(f"dm nav: deployed {path.name}")
            self.artifacts.log_step("farm_cfg_deploy")
        except Exception as exc:
            self._nav_progress(f"dm nav: farm_panel.cfg warn ({exc})")

    def _console_buy_once(self, *, label: str = "team") -> None:
        if isinstance(self.driver, SimDriver) or not self.hwnd or self._startup_buy_done:
            return
        from modules.dm_runner.autobuy import run_console_autobuy

        if run_console_autobuy(
            self.hwnd,
            attempt=1,
            total=1,
            on_progress=self._nav_progress,
            log_step=self.artifacts.log_step,
        ):
            self._startup_buy_done = True
            self._nav_progress("dm nav: autobuy startup done")
        self.artifacts.log_step("dm_autobuy_console_after_team", label=label)

    def _ensure_team_joined(self) -> None:
        """Blocking team-pick phase before map load / spawn."""
        if isinstance(self.driver, SimDriver):
            return
        from modules.dm_runner.team_join import wait_team_select_done

        wait_team_select_done(
            self.driver,
            self.coords,
            timeout_sec=float(max(120,self.config.dm_team_select_timeout_sec,self.config.map_load_delay_sec)),
            click_retry_sec=1.0,
            on_progress=self._nav_progress,
            log_step=self.artifacts.log_step,
            should_stop=self.should_stop,
        )
        self._team_done_mono = time.monotonic()

    def _spawn_hud_visible(self, img) -> bool:
        if detect_probe_key(img, self.coords, "team_select", min_match=1):
            return False
        return detect_state(
            img,
            ScreenState.IN_DM,
            self.coords,
            min_match=self.config.in_dm_min_match,
        )

    def _reload_farm_cfg_in_game(self) -> None:
        """Reload binds after redeploy (CT rifle names may differ from launch +exec)."""
        if isinstance(self.driver, SimDriver) or not self.hwnd:
            return
        from modules.ui_nav.cs2_console import run_cs2_console_commands

        try:
            run_cs2_console_commands(self.hwnd, "exec farm_panel.cfg")
            self._nav_progress("dm nav: exec farm_panel.cfg (reload binds)")
            self.artifacts.log_step("farm_cfg_exec")
        except UiNavError as exc:
            self._nav_progress(f"dm nav: exec farm_panel.cfg warn ({exc})")

    def _start_combat_preload(self) -> None:
        """Start csgobot subprocess after team console buy."""
        if self._combat_preload_started or not self.on_team_joined:
            return
        self.on_team_joined()
        self._combat_preload_started = True

    def _finish_spawn_phase(self, *, soft_peek: bool) -> None:
        """Reconfirm spawn immediately before console input and combat start."""
        self._ensure_team_joined()
        self._abort_if_stopped()
        if not self._startup_buy_done:
            self._console_buy_once(label="confirmed_spawn")
        self._start_combat_preload()
        self._e(EventType.IN_DM, self._in_dm_detail(soft_peek=soft_peek))

    def _emit_in_dm_if_already_on_frame(self) -> bool:
        """Retry fast-path: skip map_load_delay when soft/strict in_dm visible."""
        try:
            self._ensure_team_joined()
        except UiNavTimeoutError:
            pass
        img = self.driver.capture()
        if detect_probe_key(img, self.coords, "team_select", min_match=1):
            return False
        if not self._spawn_hud_visible(img):
            return False
        strict = detect_state(img, ScreenState.IN_DM, self.coords)
        if strict:
            self._nav_progress("dm nav: in_dm on frame; skip wait")
        else:
            self._nav_progress("dm nav: soft in_dm on frame; skip wait")
        self._finish_spawn_phase(soft_peek=not strict)
        return True

    def _wait_search_and_in_dm(self) -> None:
        self._confirm_search_started()

        self._set_sim_phase(ScreenState.IN_DM)
        self._ensure_team_joined()
        self._bootstrap_cs2_farm_cfg()
        self._nav_progress("dm nav: spawn ready — preparing combat")
        self._finish_spawn_phase(soft_peek=True)

    def _click_target(self, name: str) -> None:
        self._abort_if_stopped()
        before = self.driver.capture()
        on_main_before = detect_state(before, ScreenState.MAIN_MENU, self.coords)
        last_err: Exception | None = None
        for attempt in range(1, 3):
            pt = self.coords.click(name)
            if not isinstance(self.driver,SimDriver) and self.coords.base_width==1280:
                from modules.ui_nav.menu_labels import play_button,play_page,deathmatch_selected
                from modules.ui_nav.coords import Point
                current=self.driver.capture()
                if name=='main_menu_play':
                    found=play_button(current)
                    if found is None:raise UiNavError('Play label not found; click cancelled')
                    pt=Point(*found)
                elif name=='mode_deathmatch' and not play_page(current):
                    raise UiNavError('Play page not confirmed; Deathmatch click cancelled')
                elif name=='start_search' and not deathmatch_selected(current):
                    raise UiNavError('Deathmatch selection not confirmed; search click cancelled')
            self._nav_progress(f"dm click {name} @({pt.x},{pt.y})")
            try:
                self.driver.click(pt)
                if name=="start_search":self._search_requested=True
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
            if not isinstance(self.driver,SimDriver) and self.coords.base_width==1280:
                from modules.ui_nav.menu_labels import deathmatch_selected,start_button_available
                if name=='mode_deathmatch' and not deathmatch_selected(after):
                    if attempt<2:continue
                    raise UiNavError('Deathmatch tab did not become selected')
                if name=='start_search' and deathmatch_selected(after) and start_button_available(after):
                    if attempt<2:continue
                    raise UiNavError('Start button remained available; search click did not take effect')
            if name == 'main_menu_play' and not isinstance(self.driver,SimDriver) and self.coords.base_width==1280:
                from modules.ui_nav.menu_labels import play_page
                if play_page(after):return
                if attempt<2:continue
                raise UiNavError('Play click did not open the matchmaking page')
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
                    if attempt > 1 and self._emit_in_dm_if_already_on_frame():
                        return
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
                    self._reset_search()
        if last_err:
            raise last_err

    def _reset_search(self) -> None:
        """Abandon a timed-out load and confirm the menu before starting a new search."""
        self._abort_if_stopped()
        self._team_done_mono=None
        self._startup_buy_done=False
        self._combat_preload_started=False
        self._menu_nav_done=False
        if (not isinstance(self.driver,SimDriver) and getattr(self,"_search_requested",False)
                and not detect_state(self.driver.capture(),ScreenState.MAIN_MENU,self.coords)):
            from modules.ui_nav.cs2_console import run_cs2_console_commands
            from modules.ui_nav.cs2_modal_dismiss import dismiss_cs2_modals
            dismiss_cs2_modals(self.hwnd,on_progress=self._nav_progress)
            run_cs2_console_commands(self.hwnd,'disconnect')
        self._set_sim_phase(ScreenState.MAIN_MENU)
        self.wait_main_menu()
        self._search_requested=False
        self._nav_progress('dm nav: menu confirmed; restarting search')

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
