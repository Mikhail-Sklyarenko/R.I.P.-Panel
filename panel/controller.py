"""Связка UI ↔ vault ↔ config ↔ orchestrator (B3, B10)."""

from __future__ import annotations

import queue
from collections.abc import Callable
from dataclasses import replace
from typing import Any, Literal

from config.loader import load_config, save_config
from config.schema import AppConfig
from core.conveyor import build_queue
from core.orchestrator import Orchestrator
from core.session_mode import SessionMode
from core.session_state import SessionState
from modules.level_service import fetch_level
from config.paths import ensure_fsm_import_dirs
from modules.vault.fsm_import import (
    format_import_summary,
    import_from_fsm_files,
    is_import_staging_empty,
)
from modules.vault.store import list_accounts, mark_farmed_this_week
from panel.models import AccountRow

LogKind = Literal["main", "drop"]


class PanelController:
    """Thread-safe логи; аккаунты из vault; orchestrator (test или real)."""

    def __init__(self, root: Any | None, *, test_mode: bool) -> None:
        self.root = root
        self.test_mode = test_mode
        self.config = load_config()
        self.accounts: list[AccountRow] = []
        self._log_queue: queue.Queue[tuple[LogKind, str]] = queue.Queue()
        self._checkbox_vars: dict[str, Any] = {}
        self._main_log_widget: Any | None = None
        self._drop_log_widget: Any | None = None
        self._nav_metrics_widget: Any | None = None
        self._nav_metrics_poll_at: float = 0.0
        self.on_accounts_changed: Callable[[], None] | None = None
        self.on_counters_changed: Callable[[], None] | None = None
        self.on_config_paths_changed: Callable[[], None] | None = None
        self.launched_count: int = 0
        self._orchestrator = Orchestrator(
            test_mode=self._orchestrator_test_mode(),
            ui_callback=self.append_log,
            drop_callback=self.append_drop_log,
            on_session_complete=self._on_session_complete,
        )
        self.reload_accounts()

    def _orchestrator_test_mode(self) -> bool:
        return bool(self.test_mode or self.config.test_mode)

    def bind_log_widgets(self, main_log: Any, drop_log: Any) -> None:
        self._main_log_widget = main_log
        self._drop_log_widget = drop_log

    def bind_nav_metrics_widget(self, widget: Any) -> None:
        self._nav_metrics_widget = widget
        self.refresh_nav_metrics_dashboard()

    def start(self) -> None:
        from core.startup_checks import (
            collect_startup_warnings,
            format_startup_banner,
        )

        self.config = load_config()
        for line in format_startup_banner(self.config):
            self.append_log(line)
        mode = "test fakes" if self._orchestrator_test_mode() else "real modules"
        self.append_log(f"orchestrator: {mode}")
        for warn in collect_startup_warnings(self.config):
            self.append_log(f"WARN: {warn}")
        self._schedule_poll()

    def _schedule_poll(self) -> None:
        if self.root is not None:
            self.root.after(100, self._poll_logs_tick)

    def _poll_logs_tick(self) -> None:
        self._drain_log_queue()
        self._maybe_refresh_nav_metrics()
        if self.root is not None:
            self.root.after(100, self._poll_logs_tick)

    def _maybe_refresh_nav_metrics(self) -> None:
        import time

        now = time.monotonic()
        if now - self._nav_metrics_poll_at < 2.0:
            return
        self._nav_metrics_poll_at = now
        self.refresh_nav_metrics_dashboard()

    def refresh_nav_metrics_dashboard(self) -> None:
        widget = self._nav_metrics_widget
        if widget is None:
            return
        from modules.nav_metrics.aggregate import list_inbox_files
        from modules.nav_metrics.store import format_fleet_dashboard

        inbox_n = len(list_inbox_files())
        text = format_fleet_dashboard(hours=24.0, include_inbox=True)
        if inbox_n:
            text += f"\n  inbox: {inbox_n} file(s) pending import"
        status = self.nav_fleet_collector_status()
        if status.get("running"):
            text += (
                f"\n  collector: RUNNING :{status.get('port')} "
                f"ingested={status.get('ingest_count', 0)}"
            )
        else:
            text += "\n  collector: stopped (start on master PC)"
        push_url = (self.config.nav_fleet_push_url or "").strip()
        if push_url:
            text += f"\n  push_url: {push_url}"
        try:
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
            widget.configure(state="disabled")
        except Exception:
            pass

    def import_fleet_inbox_metrics(self) -> None:
        from modules.nav_metrics.aggregate import import_fleet_inbox

        result = import_fleet_inbox(archive=True)
        self.append_log(
            f"nav fleet: imported {result['imported_rows']} rows "
            f"from {result['imported_files']} file(s)"
        )
        self.refresh_nav_metrics_dashboard()

    def start_nav_fleet_collector(self) -> dict[str, Any]:
        from modules.nav_metrics.collector import NavFleetCollectorError, start_collector

        self.config = load_config()
        try:
            info = start_collector(
                port=self.config.nav_fleet_collector_port,
                token=self.config.nav_fleet_collector_token,
            )
        except NavFleetCollectorError as exc:
            self.append_log(f"nav collector: {exc}")
            return {"running": False, "error": str(exc)}
        self.append_log(f"nav collector: listening {info.get('url')}")
        return info

    def stop_nav_fleet_collector(self) -> None:
        from modules.nav_metrics.collector import stop_collector

        stop_collector()
        self.append_log("nav collector: stopped")

    def nav_fleet_collector_status(self) -> dict[str, Any]:
        from modules.nav_metrics.collector import collector_status

        return collector_status()

    def list_nav_pack_ids(self) -> list[str]:
        from modules.nav_pack.editor import list_pack_ids

        return list_pack_ids()

    def load_nav_pack_editor(self, pack_id: str):
        from modules.nav_pack.editor import load_pack_view

        return load_pack_view(pack_id)

    def save_nav_pack_override(
        self,
        pack_id: str,
        *,
        goal_x: float,
        goal_y: float,
        goal_arrive_radius: float,
        goal2_x: float,
        goal2_y: float,
        goal2_arrive_radius: float,
        dwell_at_goal_sec: float,
        direct_goal_dist: float,
    ) -> None:
        from modules.nav_pack.editor import save_pack_override

        path = save_pack_override(
            pack_id,
            goal_x=goal_x,
            goal_y=goal_y,
            goal_arrive_radius=goal_arrive_radius,
            goal2_x=goal2_x,
            goal2_y=goal2_y,
            goal2_arrive_radius=goal2_arrive_radius,
            dwell_at_goal_sec=dwell_at_goal_sec,
            direct_goal_dist=direct_goal_dist,
        )
        self.append_log(f"nav pack: saved override → {path}")

    def reset_nav_pack_override(self, pack_id: str) -> None:
        from modules.nav_pack.editor import reset_pack_override

        if reset_pack_override(pack_id):
            self.append_log(f"nav pack: reset override for {pack_id} (using bundled)")
        else:
            self.append_log(f"nav pack: no override for {pack_id}")

    def validate_nav_pack(self, pack_id: str) -> None:
        from modules.combat import csgobot_ai

        ok, info = csgobot_ai.check_nav_preflight(pack_id)
        if ok:
            ver = info.get("pack_version") or "?"
            self.append_log(f"nav pack: {pack_id} preflight ok v{ver}")
        else:
            errs = info.get("errors") or info.get("error") or "failed"
            if isinstance(errs, list):
                errs = "; ".join(str(e) for e in errs[:2])
            self.append_log(f"nav pack: {pack_id} preflight FAILED — {errs}")

    def reload_accounts(self) -> None:
        self.config = load_config()
        prev_selected = set(self.get_selected_logins())
        self.accounts = self._load_account_rows()
        for row in self.accounts:
            if row.login in prev_selected:
                row.selected = True
        self._checkbox_vars = {row.login: None for row in self.accounts}
        self._notify_accounts()
        self._notify_counters()

    def _load_account_rows(self) -> list[AccountRow]:
        try:
            entries = list_accounts()
        except (ValueError, OSError):
            entries = []

        if entries:
            return [
                AccountRow(
                    login=e.login,
                    level=e.level,
                    xp=e.xp,
                    farmed_this_week=e.farmed_this_week,
                    status="done" if e.farmed_this_week else "idle",
                )
                for e in entries
            ]

        if self.test_mode and self._use_test_mode_mock_accounts():
            return [
                AccountRow(login=f"mock_acc_{i}", level=0, xp=0, status="idle")
                for i in range(1, 4)
            ]
        return []

    def _use_test_mode_mock_accounts(self) -> bool:
        """Mock acc только если vault и import staging пусты."""
        try:
            if list_accounts():
                return False
        except (ValueError, OSError):
            pass
        self.config = load_config()
        return is_import_staging_empty(self.config)

    @property
    def selected_count(self) -> int:
        return len(self.get_selected_logins())

    @property
    def farmed_count(self) -> int:
        return sum(1 for a in self.accounts if a.farmed_this_week)

    def get_selected_logins(self) -> list[str]:
        selected: list[str] = []
        for login, var in self._checkbox_vars.items():
            if var is not None and var.get():
                selected.append(login)
        return selected

    def register_checkbox(self, login: str, var: Any) -> None:
        self._checkbox_vars[login] = var
        try:
            var.trace_add("write", lambda *_a: self._notify_counters())
        except (AttributeError, TypeError):
            pass

    def append_log(self, message: str) -> None:
        self._log_queue.put(("main", message))

    def append_drop_log(self, message: str) -> None:
        self._log_queue.put(("drop", message))

    def _drain_log_queue(self) -> None:
        while True:
            try:
                kind, message = self._log_queue.get_nowait()
            except queue.Empty:
                break
            line = f"{message}\n"
            if kind == "main":
                self._insert_text(self._main_log_widget, line)
            else:
                self._insert_text(self._drop_log_widget, line)

    @staticmethod
    def _insert_text(widget: Any | None, line: str) -> None:
        if widget is None:
            return
        widget.configure(state="normal")
        widget.insert("end", line)
        widget.see("end")
        widget.configure(state="disabled")

    def apply_appearance(self) -> None:
        import customtkinter as ctk

        mode = self.config.appearance_mode
        if mode in ("dark", "light", "system"):
            ctk.set_appearance_mode(mode)
        scaling = self.config.gui_scaling.rstrip("%") or "100"
        try:
            factor = int(scaling) / 100.0
        except ValueError:
            factor = 1.0
        ctk.set_widget_scaling(factor)
        ctk.set_window_scaling(factor)

    def save_config_from_ui(self, updates: dict[str, Any]) -> None:
        self.config = self.config.model_copy(update=updates)
        save_config(self.config)
        self.apply_appearance()
        self.append_log("config saved → data/config.yaml")

    def pick_steam_path(self) -> None:
        from panel.path_picker import (
            STEAM_EXE_NAMES,
            default_steam_initialdir,
            path_picker_available,
            pick_executable,
        )

        if not path_picker_available():
            self.append_log(
                "WARN: path picker Windows-only — set steam_path in data/config.yaml"
            )
            return
        self.config = load_config()
        chosen = pick_executable(
            parent=self.root,
            title="Select steam.exe",
            initialdir=default_steam_initialdir(self.config.steam_path),
            expected_basenames=STEAM_EXE_NAMES,
        )
        if chosen:
            self._apply_executable_path("steam_path", chosen)

    def pick_cs2_path(self) -> None:
        from panel.path_picker import (
            CS2_EXE_NAMES,
            default_cs2_initialdir,
            path_picker_available,
            pick_executable,
        )

        if not path_picker_available():
            self.append_log(
                "WARN: path picker Windows-only — set cs2_path in data/config.yaml"
            )
            return
        self.config = load_config()
        chosen = pick_executable(
            parent=self.root,
            title=(
                "Select cs2.exe (Counter-Strike …\\game\\bin\\win64)"
            ),
            initialdir=default_cs2_initialdir(
                self.config.cs2_path, self.config.steam_path
            ),
            expected_basenames=CS2_EXE_NAMES,
        )
        if chosen:
            self._apply_executable_path("cs2_path", chosen)

    def _apply_executable_path(self, field: str, path: str) -> None:
        self.config = self.config.model_copy(update={field: path})
        save_config(self.config)
        self.append_log(f"{field} set: {path}")
        if self.on_config_paths_changed:
            self.on_config_paths_changed()

    def _on_session_complete(
        self,
        login: str,
        final: SessionState,
        mode: SessionMode,
    ) -> None:
        if final is SessionState.DONE and mode is SessionMode.FULL:
            try:
                mark_farmed_this_week(login)
            except Exception as exc:
                self.append_log(f"[{login}] farmed flag: {exc}")
        self.launched_count = self._orchestrator.launched_count
        self.reload_accounts()

    def _notify_accounts(self) -> None:
        if self.on_accounts_changed:
            self.on_accounts_changed()

    def _notify_counters(self) -> None:
        if self.on_counters_changed:
            self.on_counters_changed()

    # --- Farm control (B10) ---

    def start_farm(self) -> None:
        """Конвейер: все unfarmed (или выбранные, если есть галочки)."""
        sel = self.get_selected_logins()
        if sel:
            self.start_selected()
            return
        queue = build_queue()
        if not queue:
            self.append_log("start_farm: all accounts farmed this week")
            return
        self._enqueue_farm(queue)

    def start_selected(self) -> None:
        sel = self.get_selected_logins()
        if not sel:
            self.append_log("start_selected: no accounts checked")
            return
        queue = build_queue(selected=sel, only_unfarmed=False)
        if not queue:
            self.append_log("start_selected: nothing to queue")
            return
        self._enqueue_farm(queue)

    def launch_selected(self) -> None:
        sel = self.get_selected_logins()
        if not sel:
            self.append_log("launch_selected: no accounts checked")
            return
        cfg = load_config()
        if cfg.start_farm_when_launched:
            self._enqueue_farm(sel, force_farm=True)
            self.append_log("launch_selected: start_farm_when_launched → full farm")
            return
        self._orchestrator.enqueue(sel, mode=SessionMode.LAUNCH_ONLY)
        self._mark_status(sel, "launched")
        self.launched_count = self._orchestrator.launched_count
        self._notify_counters()

    def _enqueue_farm(self, logins: list[str], *, force_farm: bool = True) -> None:
        cfg = load_config()
        if cfg.auto_collect_drop and not (cfg.trade_offer_link or "").strip():
            self.append_log(
                "WARN: trade_offer_link empty — LOOT WILL FAIL at end; set in Config #1"
            )
        self._mark_status(logins, "farming")
        self._orchestrator.enqueue(
            logins,
            mode=SessionMode.FULL,
            force_farm=force_farm,
        )
        self.launched_count = self._orchestrator.launched_count
        self._notify_counters()

    def stop_farm(self) -> None:
        self._orchestrator.stop()
        self.append_log("stop_farm: orchestrator stop requested")

    def get_lvl_selected(self) -> None:
        sel = self.get_selected_logins()
        if not sel:
            self.append_log("get_lvl: no accounts checked")
            return
        for login in sel:
            try:
                snap = fetch_level(login)
                self.append_log(
                    f"get_lvl [{login}] level={snap.level} xp={snap.xp} ({snap.source})"
                )
            except Exception as exc:
                self.append_log(f"get_lvl [{login}] failed: {exc}")
        self.reload_accounts()

    def refresh_accounts(self) -> None:
        self.config = load_config()
        if self.config.fsm_import_on_refresh and self.config.fsm_import_enabled:
            self.import_from_logpass(quiet_summary=True)
        self.reload_accounts()
        self.append_log(
            f"accounts refreshed: {len(self.accounts)} | "
            f"Selected {self.selected_count} | "
            f"Launched {self.launched_count} | "
            f"Farmed {self.farmed_count}"
        )

    def import_from_logpass(self, *, quiet_summary: bool = False) -> None:
        self.config = load_config()
        if not self.config.fsm_import_enabled:
            self.append_log("import: disabled (fsm_import_enabled=false)")
            return
        results = import_from_fsm_files(cfg=self.config)
        for line in format_import_summary(results):
            if quiet_summary and line.startswith("import:"):
                continue
            self.append_log(line)
        if not quiet_summary:
            for row in results:
                if row.status == "skipped" and row.login:
                    self.append_log(f"import skip [{row.login}]: {row.detail}")
        self.reload_accounts()

    def open_import_folder(self) -> None:
        import os
        import subprocess
        import sys

        folder = ensure_fsm_import_dirs()
        path = str(folder.resolve())
        self.append_log(f"import folder: {path}")
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
        except OSError as exc:
            self.append_log(f"open import folder failed: {exc}")

    def _mark_status(self, logins: list[str], status: str) -> None:
        sel = set(logins)
        self.accounts = [
            replace(row, status=status if row.login in sel else row.status)
            for row in self.accounts
        ]
        self._notify_accounts()

    def move_all_cs_windows(self) -> None:
        from modules.utils import UtilsError, UtilsPlatformError, recover_move_windows

        self.config = load_config()
        try:
            result = recover_move_windows(config=self.config)
            titles = ", ".join(w.title[:24] for w in result.moved[:4])
            extra = f" … +{result.count - 4}" if result.count > 4 else ""
            sim = " (sim)" if result.simulated else ""
            self.append_log(
                f"utils: moved {result.count} window(s) "
                f"{result.width}x{result.height}{sim}"
            )
            if titles:
                self.append_log(f"  {titles}{extra}")
        except (UtilsError, UtilsPlatformError) as exc:
            self.append_log(f"utils move failed: {exc}")

    def kill_all_cs_steam(self) -> None:
        from modules.utils import UtilsError, UtilsPlatformError, recover_hang

        self.config = load_config()

        def _stop_orch() -> None:
            if self._orchestrator:
                self._orchestrator.stop()
                self.append_log("utils: orchestrator stop (recovery)")

        try:
            result = recover_hang(
                parent=self.root,
                config=self.config,
                on_before_kill=_stop_orch,
            )
            if not result.kill.ok:
                self.append_log("utils: kill cancelled")
                return
            self.append_log(f"utils: recovery kill — {result.kill.summary()}")
        except (UtilsError, UtilsPlatformError) as exc:
            self.append_log(f"utils kill failed: {exc}")

    def clear_logs(self) -> None:
        for widget in (self._main_log_widget, self._drop_log_widget):
            if widget is None:
                continue
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.configure(state="disabled")
        self.append_log("logs cleared")

    def test_telegram(self) -> None:
        from modules.telegram import TelegramError, send_test_ping

        self.config = load_config()
        try:
            result = send_test_ping(self.config)
            self.append_log(
                f"telegram test: {result.method} — {result.detail}"
            )
        except TelegramError as exc:
            self.append_log(f"telegram test failed: {exc}")

    # Legacy stubs for tests
    def stub_start_farm(self) -> None:
        self.start_farm()

    def stub_stop_farm(self) -> None:
        self.stop_farm()

    def stub_launch_selected(self) -> None:
        self.launch_selected()

    def stub_refresh_accounts(self) -> None:
        self.refresh_accounts()

    def mark_selected_farming(self) -> None:
        self._mark_status(self.get_selected_logins(), "farming")

    def stub_utils_clear_logs(self) -> None:
        self.clear_logs()
