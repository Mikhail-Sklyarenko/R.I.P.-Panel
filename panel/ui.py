"""FSM-like layout: left logs/TG, center main+accounts, right controls/config."""

from __future__ import annotations

import sys

import customtkinter as ctk

from config.schema import BotMode
from panel.controller import PanelController
from panel.icon import apply_window_icon
from panel.nav_radar_editor import NavRadarEditor
from panel.path_picker import path_picker_available, truncate_path


class PanelView:
    def __init__(self, root: ctk.CTk, controller: PanelController) -> None:
        self.root = root
        self.ctrl = controller
        self.ctrl.on_accounts_changed = self.refresh_account_list
        self.ctrl.on_counters_changed = self.refresh_counters
        self.ctrl.on_config_paths_changed = self._refresh_path_labels
        self._steam_path_label: ctk.CTkLabel | None = None
        self._cs2_path_label: ctk.CTkLabel | None = None
        self._vars: dict[str, ctk.Variable] = {}
        self._counters_label: ctk.CTkLabel | None = None
        self._config2_frame: ctk.CTkFrame | None = None
        self._accounts_scroll: ctk.CTkScrollableFrame | None = None

    def build(self) -> None:
        self.ctrl.apply_appearance()
        geo = self.ctrl.config.panel_geometry
        if "x" in geo:
            self.root.geometry(geo)
        else:
            self.root.geometry(f"{geo}+80+80")
        self.root.title("Farm Panel")
        apply_window_icon(self.root)
        self.root.minsize(960, 560)

        self.root.grid_columnconfigure(0, weight=2, minsize=200)
        self.root.grid_columnconfigure(1, weight=5, minsize=420)
        self.root.grid_columnconfigure(2, weight=3, minsize=280)
        self.root.grid_rowconfigure(0, weight=1)

        self._build_left(0)
        self._build_center(1)
        self._build_right(2)

        drop_log = self._drop_log
        main_log = self._main_log
        self.ctrl.bind_log_widgets(main_log, drop_log)
        self.refresh_account_list()
        self.refresh_counters()
        self._show_config2(False)

    def _build_left(self, col: int) -> None:
        frame = ctk.CTkFrame(self.root)
        frame.grid(row=0, column=col, sticky="nsew", padx=(8, 4), pady=8)
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(frame, text="Drop log", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="w", padx=8, pady=(8, 4)
        )
        self._drop_log = ctk.CTkTextbox(frame, height=200, state="disabled")
        self._drop_log.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)

        ctk.CTkButton(
            frame,
            text="Telegram",
            command=self._toggle_config2,
        ).grid(row=2, column=0, sticky="ew", padx=8, pady=6)

        app_frame = ctk.CTkFrame(frame, fg_color="transparent")
        app_frame.grid(row=3, column=0, sticky="ew", padx=8, pady=8)
        ctk.CTkLabel(app_frame, text="Appearance", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w"
        )
        self._vars["appearance_mode"] = ctk.StringVar(
            value=self.ctrl.config.appearance_mode
        )
        ctk.CTkOptionMenu(
            app_frame,
            values=["dark", "light", "system"],
            variable=self._vars["appearance_mode"],
        ).pack(fill="x", pady=4)
        self._vars["gui_scaling"] = ctk.StringVar(value=self.ctrl.config.gui_scaling)
        ctk.CTkOptionMenu(
            app_frame,
            values=["80%", "90%", "100%", "110%", "125%"],
            variable=self._vars["gui_scaling"],
        ).pack(fill="x", pady=4)
        ctk.CTkButton(
            app_frame,
            text="Apply appearance",
            command=self._save_appearance,
        ).pack(fill="x", pady=4)

    def _build_center(self, col: int) -> None:
        frame = ctk.CTkFrame(self.root)
        frame.grid(row=0, column=col, sticky="nsew", padx=4, pady=8)
        frame.grid_rowconfigure(1, weight=2)
        frame.grid_rowconfigure(3, weight=3)
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(frame, text="Main log", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="w", padx=8, pady=(8, 4)
        )
        self._main_log = ctk.CTkTextbox(frame, state="disabled")
        self._main_log.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)

        ctk.CTkLabel(
            frame, text="Nav fleet (24h)", font=ctk.CTkFont(weight="bold")
        ).grid(row=2, column=0, sticky="w", padx=8, pady=(8, 4))
        self._nav_metrics_log = ctk.CTkTextbox(frame, height=120, state="disabled")
        self._nav_metrics_log.grid(row=3, column=0, sticky="nsew", padx=8, pady=4)
        frame.grid_rowconfigure(3, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=4, column=0, sticky="ew", padx=8, pady=(8, 0))
        ctk.CTkLabel(
            header, text="Accounts", font=ctk.CTkFont(weight="bold")
        ).pack(side="left")
        ctk.CTkLabel(
            header,
            text="  ☐  #   login          LVL   XP   status",
            text_color="gray60",
            font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=8)

        self._accounts_scroll = ctk.CTkScrollableFrame(frame, height=220)
        self._accounts_scroll.grid(row=3, column=0, sticky="nsew", padx=8, pady=4)
        self._accounts_scroll.grid_columnconfigure(5, weight=1)

    def _build_right(self, col: int) -> None:
        frame = ctk.CTkFrame(self.root)
        frame.grid(row=0, column=col, sticky="nsew", padx=(4, 8), pady=8)
        frame.grid_columnconfigure(0, weight=1)

        row = 0
        row = self._section_accounts_control(frame, row)
        row = self._section_utils(frame, row)
        row = self._section_config_tabs(frame, row)

    def _section_accounts_control(self, parent: ctk.CTkFrame, row: int) -> int:
        box = ctk.CTkFrame(parent)
        box.grid(row=row, column=0, sticky="ew", padx=4, pady=4)
        ctk.CTkLabel(
            box, text="Accounts Control", font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=8, pady=(8, 4))
        self._counters_label = ctk.CTkLabel(
            box,
            text="Selected: 0 | Launched: 0 | Farmed: 0",
            font=ctk.CTkFont(size=12),
            text_color="gray70",
        )
        self._counters_label.pack(anchor="w", padx=8, pady=(4, 6))
        for text, cmd in (
            ("Start Farm", self._on_start_farm),
            ("Start Selected", self._on_start_selected),
            ("Stop Farm", self.ctrl.stop_farm),
            ("Launch Selected", self._on_launch_selected),
            ("Get LVL", self._on_get_lvl),
            ("Refresh accounts", self.ctrl.refresh_accounts),
        ):
            ctk.CTkButton(box, text=text, command=cmd).pack(fill="x", padx=8, pady=3)
        return row + 1

    def _section_utils(self, parent: ctk.CTkFrame, row: int) -> int:
        box = ctk.CTkFrame(parent)
        box.grid(row=row, column=0, sticky="ew", padx=4, pady=4)
        ctk.CTkLabel(box, text="Utils #1", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=8, pady=(8, 4)
        )
        ctk.CTkButton(
            box,
            text="Import from logpass",
            command=self.ctrl.import_from_logpass,
        ).pack(fill="x", padx=8, pady=3)
        ctk.CTkButton(
            box,
            text="Open import folder",
            command=self.ctrl.open_import_folder,
        ).pack(fill="x", padx=8, pady=3)
        ctk.CTkButton(
            box,
            text="Test Telegram",
            command=self.ctrl.test_telegram,
        ).pack(fill="x", padx=8, pady=3)
        ctk.CTkButton(
            box,
            text="Move all CS windows",
            command=self.ctrl.move_all_cs_windows,
        ).pack(fill="x", padx=8, pady=3)
        ctk.CTkButton(
            box,
            text="Kill ALL CS & Steam",
            command=self.ctrl.kill_all_cs_steam,
        ).pack(fill="x", padx=8, pady=3)
        ctk.CTkButton(
            box,
            text="Clear logs",
            command=self.ctrl.clear_logs,
        ).pack(fill="x", padx=8, pady=3)
        return row + 1

    def _section_config_tabs(self, parent: ctk.CTkFrame, row: int) -> int:
        outer = ctk.CTkFrame(parent)
        outer.grid(row=row, column=0, sticky="nsew", padx=4, pady=4)
        parent.grid_rowconfigure(row, weight=1)
        tabs = ctk.CTkTabview(outer, height=380)
        tabs.pack(fill="both", expand=True, padx=4, pady=4)
        tabs.add("Config #1")
        tabs.add("Config #2")
        tabs.add("Config #3")
        tabs.add("Nav Fleet")
        tabs.add("Nav Packs")
        self._build_config1(tabs.tab("Config #1"))
        self._config2_frame = tabs.tab("Config #2")
        self._build_config2(self._config2_frame)
        self._build_config3(tabs.tab("Config #3"))
        self._build_nav_fleet(tabs.tab("Nav Fleet"))
        self._build_nav_packs(tabs.tab("Nav Packs"))
        return row + 1

    def _build_config1(self, parent: ctk.CTkFrame) -> None:
        scroll = ctk.CTkScrollableFrame(parent)
        scroll.pack(fill="both", expand=True, padx=4, pady=4)
        self._build_executable_paths(scroll)
        cfg = self.ctrl.config
        self._add_entry(scroll, "trade_offer_link", cfg.trade_offer_link)
        self._add_entry(
            scroll,
            "cs2_sensitivity",
            str(getattr(cfg, "cs2_sensitivity", 2.1)),
        )
        ctk.CTkLabel(
            scroll,
            text="CS2 console: sensitivity → csgobot X360",
            text_color="gray55",
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=8, pady=(0, 4))
        self._add_switch(scroll, "auto_collect_drop", cfg.auto_collect_drop)
        self._add_switch(
            scroll, "start_farm_when_launched", cfg.start_farm_when_launched
        )
        self._add_switch(scroll, "only_launch_steam", cfg.only_launch_steam)
        self._add_switch(scroll, "steam_auto_login", cfg.steam_auto_login)
        self._vars["steam_login_mode"] = ctk.StringVar(
            value=getattr(cfg, "steam_login_mode", "gui")
        )
        ctk.CTkLabel(scroll, text="steam_login_mode").pack(anchor="w", padx=8, pady=(6, 0))
        ctk.CTkOptionMenu(
            scroll,
            values=["gui", "api", "gui_then_api"],
            variable=self._vars["steam_login_mode"],
        ).pack(fill="x", padx=8, pady=2)
        self._add_switch(
            scroll, "steam_kill_before_login", cfg.steam_kill_before_login
        )
        ctk.CTkButton(
            scroll,
            text="Save Config #1",
            command=self._save_config1,
        ).pack(fill="x", padx=8, pady=8)

    def _build_executable_paths(self, parent: ctk.CTkFrame) -> None:
        picker_state = "normal" if path_picker_available() else "disabled"
        ctk.CTkButton(
            parent,
            text="Set Steam path",
            state=picker_state,
            command=self.ctrl.pick_steam_path,
        ).pack(fill="x", padx=8, pady=(8, 2))
        self._steam_path_label = ctk.CTkLabel(
            parent,
            text=truncate_path(self.ctrl.config.steam_path),
            anchor="w",
            text_color="gray70",
            wraplength=260,
        )
        self._steam_path_label.pack(fill="x", padx=8, pady=(0, 6))
        ctk.CTkButton(
            parent,
            text="Set CS2 path",
            state=picker_state,
            command=self.ctrl.pick_cs2_path,
        ).pack(fill="x", padx=8, pady=(4, 2))
        self._cs2_path_label = ctk.CTkLabel(
            parent,
            text=truncate_path(self.ctrl.config.cs2_path),
            anchor="w",
            text_color="gray70",
            wraplength=260,
        )
        self._cs2_path_label.pack(fill="x", padx=8, pady=(0, 8))
        if sys.platform != "win32":
            ctk.CTkLabel(
                parent,
                text="Path picker: Windows only (edit data/config.yaml)",
                text_color="gray55",
                font=ctk.CTkFont(size=11),
            ).pack(anchor="w", padx=8, pady=(0, 4))

    def _refresh_path_labels(self) -> None:
        cfg = self.ctrl.config
        if self._steam_path_label is not None:
            self._steam_path_label.configure(text=truncate_path(cfg.steam_path))
        if self._cs2_path_label is not None:
            self._cs2_path_label.configure(text=truncate_path(cfg.cs2_path))

    def _build_config2(self, parent: ctk.CTkFrame) -> None:
        cfg = self.ctrl.config
        self._add_entry(parent, "telegram_bot_token", cfg.telegram_bot_token, show="*")
        self._add_entry(parent, "telegram_chat_id", cfg.telegram_chat_id)
        self._add_switch(
            parent, "telegram_send_screenshot", cfg.telegram_send_screenshot
        )
        self._add_entry(
            parent,
            "autofarm_timer_minutes",
            str(cfg.autofarm_timer_minutes),
        )
        ctk.CTkButton(
            parent,
            text="Save Config #2",
            command=self._save_config2,
        ).pack(fill="x", padx=8, pady=8)

    def _build_config3(self, parent: ctk.CTkFrame) -> None:
        cfg = self.ctrl.config
        self._add_entry(
            parent,
            "cooldown_between_accounts_sec",
            str(cfg.cooldown_between_accounts_sec),
        )
        self._add_entry(parent, "max_dm_minutes", str(cfg.max_dm_minutes))
        self._add_entry(
            parent,
            "cs2_fps_limit_nvidia",
            str(cfg.cs2_fps_limit_nvidia),
        )
        self._add_entry(parent, "proxy_expected_ip", cfg.proxy_expected_ip)
        self._add_switch(
            parent, "steam_classic_login_ui", getattr(cfg, "steam_classic_login_ui", True)
        )
        self._add_entry(parent, "fsm_logpass_path", cfg.fsm_logpass_path)
        self._add_entry(parent, "fsm_mafiles_dir", cfg.fsm_mafiles_dir)
        self._vars["bot_mode"] = ctk.StringVar(
            value=cfg.bot_mode.value if hasattr(cfg.bot_mode, "value") else str(cfg.bot_mode)
        )
        ctk.CTkLabel(parent, text="bot_mode").pack(anchor="w", padx=8, pady=(4, 0))
        ctk.CTkOptionMenu(
            parent,
            values=[BotMode.AUTO.value, BotMode.AI.value, BotMode.SIMPLE.value],
            variable=self._vars["bot_mode"],
        ).pack(fill="x", padx=8, pady=2)
        self._add_switch(
            parent,
            "csgobot_require_cuda",
            getattr(cfg, "csgobot_require_cuda", False),
        )
        self._add_switch(
            parent,
            "csgobot_nav_enabled",
            getattr(cfg, "csgobot_nav_enabled", True),
        )
        self._add_entry(
            parent,
            "csgobot_nav_pack",
            getattr(cfg, "csgobot_nav_pack", "auto"),
        )
        self._add_entry(
            parent,
            "nav_fleet_push_url",
            getattr(cfg, "nav_fleet_push_url", ""),
        )
        self._add_entry(
            parent,
            "nav_fleet_collector_port",
            str(getattr(cfg, "nav_fleet_collector_port", 8765)),
        )
        self._add_entry(
            parent,
            "nav_fleet_collector_token",
            getattr(cfg, "nav_fleet_collector_token", ""),
            show="*",
        )
        ctk.CTkButton(
            parent,
            text="Save Config #3",
            command=self._save_config3,
        ).pack(fill="x", padx=8, pady=8)

    def _build_nav_fleet(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkLabel(
            parent,
            text="Fleet nav metrics (data/logs/nav_metrics.jsonl)",
            font=ctk.CTkFont(weight="bold"),
        ).pack(anchor="w", padx=8, pady=(8, 4))
        self._nav_metrics_log = ctk.CTkTextbox(parent, height=240, state="disabled")
        self._nav_metrics_log.pack(fill="both", expand=True, padx=8, pady=4)
        collector_row = ctk.CTkFrame(parent, fg_color="transparent")
        collector_row.pack(fill="x", padx=8, pady=(0, 4))
        ctk.CTkButton(
            collector_row,
            text="Start collector (master)",
            command=self._start_nav_collector,
        ).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkButton(
            collector_row,
            text="Stop collector",
            command=self.ctrl.stop_nav_fleet_collector,
        ).pack(side="left", expand=True, fill="x", padx=(4, 0))
        ctk.CTkButton(
            parent,
            text="Refresh now",
            command=self.ctrl.refresh_nav_metrics_dashboard,
        ).pack(fill="x", padx=8, pady=(0, 4))
        ctk.CTkButton(
            parent,
            text="Import fleet inbox",
            command=self.ctrl.import_fleet_inbox_metrics,
        ).pack(fill="x", padx=8, pady=(0, 8))
        self.ctrl.bind_nav_metrics_widget(self._nav_metrics_log)

    def _build_nav_packs(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkLabel(
            parent,
            text="Nav pack editor (saves to data/nav_packs/)",
            font=ctk.CTkFont(weight="bold"),
        ).pack(anchor="w", padx=8, pady=(8, 4))

        body = ctk.CTkFrame(parent, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=4, pady=4)
        left = ctk.CTkFrame(body, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side="right", anchor="n")

        pack_ids = self.ctrl.list_nav_pack_ids() or ["dust2_dm"]
        self._vars["nav_pack_id"] = ctk.StringVar(value=pack_ids[0])
        ctk.CTkLabel(left, text="pack_id").pack(anchor="w", padx=8)
        pack_menu = ctk.CTkOptionMenu(
            left,
            values=pack_ids,
            variable=self._vars["nav_pack_id"],
            command=self._on_nav_pack_selected,
        )
        pack_menu.pack(fill="x", padx=8, pady=2)

        self._nav_pack_info = ctk.CTkLabel(left, text="", anchor="w", justify="left")
        self._nav_pack_info.pack(fill="x", padx=8, pady=4)

        fields = [
            ("goal_x", "0.52"),
            ("goal_y", "0.48"),
            ("goal_arrive_radius", "0.06"),
            ("goal2_x", "0.80"),
            ("goal2_y", "0.16"),
            ("goal2_arrive_radius", "0.06"),
            ("dwell_at_goal_sec", "35"),
            ("direct_goal_dist", "0.12"),
        ]
        for key, default in fields:
            self._add_entry(left, key, default)

        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.pack(fill="x", padx=8, pady=8)
        ctk.CTkButton(btn_row, text="Load", command=lambda: self._load_nav_pack_editor()).pack(
            side="left", expand=True, fill="x", padx=(0, 4)
        )
        ctk.CTkButton(btn_row, text="Save override", command=self._save_nav_pack).pack(
            side="left", expand=True, fill="x", padx=4
        )
        ctk.CTkButton(btn_row, text="Reset", command=self._reset_nav_pack).pack(
            side="left", expand=True, fill="x", padx=(4, 0)
        )
        ctk.CTkButton(
            left,
            text="Validate preflight",
            command=self._validate_nav_pack,
        ).pack(fill="x", padx=8, pady=(0, 8))

        self._nav_radar = NavRadarEditor(
            right,
            display_size=300,
            on_coords_changed=self._on_nav_radar_click,
        )
        self._nav_radar.pack(padx=4, pady=4)

        for key in ("goal_x", "goal_y", "goal2_x", "goal2_y"):
            self._vars[key].trace_add("write", lambda *_a: self._refresh_nav_radar())

        self._load_nav_pack_editor(pack_ids[0])

    def _start_nav_collector(self) -> None:
        self.ctrl.start_nav_fleet_collector()
        self.ctrl.refresh_nav_metrics_dashboard()

    def _on_nav_radar_click(self, target: str, x: float, y: float) -> None:
        if target == "goal1":
            self._vars["goal_x"].set(str(x))
            self._vars["goal_y"].set(str(y))
        else:
            self._vars["goal2_x"].set(str(x))
            self._vars["goal2_y"].set(str(y))
        self._refresh_nav_radar()

    def _refresh_nav_radar(self) -> None:
        if not hasattr(self, "_nav_radar"):
            return
        pid_var = self._vars.get("nav_pack_id")
        if pid_var is None:
            return
        try:
            self._nav_radar.set_pack(
                pid_var.get().strip(),
                goal_x=float(self._vars["goal_x"].get()),
                goal_y=float(self._vars["goal_y"].get()),
                goal2_x=float(self._vars["goal2_x"].get()),
                goal2_y=float(self._vars["goal2_y"].get()),
            )
        except (ValueError, TypeError):
            return

    def _on_nav_pack_selected(self, pack_id: str) -> None:
        self._load_nav_pack_editor(pack_id)

    def _load_nav_pack_editor(self, pack_id: str | None = None) -> None:
        pid = (pack_id or self._vars.get("nav_pack_id", ctk.StringVar(value="dust2_dm")).get()).strip()
        try:
            view = self.ctrl.load_nav_pack_editor(pid)
        except Exception as exc:
            self.ctrl.append_log(f"nav pack: load failed — {exc}")
            return
        self._vars["goal_x"].set(str(view.goal_x))
        self._vars["goal_y"].set(str(view.goal_y))
        self._vars["goal_arrive_radius"].set(str(view.goal_arrive_radius))
        self._vars["goal2_x"].set(str(view.goal2_x))
        self._vars["goal2_y"].set(str(view.goal2_y))
        self._vars["goal2_arrive_radius"].set(str(view.goal2_arrive_radius))
        self._vars["dwell_at_goal_sec"].set(str(view.dwell_at_goal_sec))
        self._vars["direct_goal_dist"].set(str(view.direct_goal_dist))
        self._nav_pack_info.configure(
            text=(
                f"{view.pack_id} v{view.version} ({view.source})\n"
                f"map={view.map_id} strategy={view.strategy}\n"
                f"goals: {view.goal_id}"
                + (f", {view.goal2_id}" if view.goal2_id else "")
            )
        )
        if hasattr(self, "_nav_radar"):
            self._nav_radar.set_pack(
                pid,
                goal_x=view.goal_x,
                goal_y=view.goal_y,
                goal2_x=view.goal2_x,
                goal2_y=view.goal2_y,
            )

    def _save_nav_pack(self) -> None:
        pid = self._vars["nav_pack_id"].get().strip()
        try:
            self.ctrl.save_nav_pack_override(
                pid,
                goal_x=float(self._vars["goal_x"].get()),
                goal_y=float(self._vars["goal_y"].get()),
                goal_arrive_radius=float(self._vars["goal_arrive_radius"].get()),
                goal2_x=float(self._vars["goal2_x"].get()),
                goal2_y=float(self._vars["goal2_y"].get()),
                goal2_arrive_radius=float(self._vars["goal2_arrive_radius"].get()),
                dwell_at_goal_sec=float(self._vars["dwell_at_goal_sec"].get()),
                direct_goal_dist=float(self._vars["direct_goal_dist"].get()),
            )
            self._load_nav_pack_editor(pid)
        except (ValueError, TypeError) as exc:
            self.ctrl.append_log(f"nav pack: invalid values — {exc}")

    def _reset_nav_pack(self) -> None:
        pid = self._vars["nav_pack_id"].get().strip()
        self.ctrl.reset_nav_pack_override(pid)
        self._load_nav_pack_editor(pid)

    def _validate_nav_pack(self) -> None:
        pid = self._vars["nav_pack_id"].get().strip()
        self.ctrl.validate_nav_pack(pid)

    def _add_entry(
        self,
        parent: ctk.CTkFrame,
        key: str,
        value: str,
        *,
        show: str | None = None,
    ) -> None:
        ctk.CTkLabel(parent, text=key).pack(anchor="w", padx=8, pady=(6, 0))
        var = ctk.StringVar(value=value)
        self._vars[key] = var
        kw: dict = {"textvariable": var}
        if show:
            kw["show"] = show
        ctk.CTkEntry(parent, **kw).pack(fill="x", padx=8, pady=2)

    def _add_switch(self, parent: ctk.CTkFrame, key: str, value: bool) -> None:
        var = ctk.BooleanVar(value=value)
        self._vars[key] = var
        ctk.CTkSwitch(parent, text=key, variable=var).pack(anchor="w", padx=8, pady=4)

    def refresh_account_list(self) -> None:
        scroll = self._accounts_scroll
        if scroll is None:
            return
        for child in scroll.winfo_children():
            child.destroy()

        for idx, row in enumerate(self.ctrl.accounts, start=1):
            var = ctk.BooleanVar(value=row.selected)
            self.ctrl.register_checkbox(row.login, var)
            line = ctk.CTkFrame(scroll, fg_color="transparent")
            line.grid(row=idx - 1, column=0, sticky="ew", pady=1)
            line.grid_columnconfigure(2, weight=1)

            ctk.CTkCheckBox(line, text="", variable=var, width=28).grid(
                row=0, column=0, padx=(0, 4)
            )
            ctk.CTkLabel(line, text=f"{idx:>2}", width=24).grid(row=0, column=1)
            ctk.CTkLabel(line, text=row.login, anchor="w").grid(
                row=0, column=2, sticky="ew", padx=4
            )
            ctk.CTkLabel(line, text=str(row.level), width=36).grid(row=0, column=3)
            ctk.CTkLabel(line, text=str(row.xp), width=40).grid(row=0, column=4)
            status_text = "farmed" if row.farmed_this_week else row.status
            status = ctk.CTkLabel(
                line,
                text=status_text,
                text_color=row.status_color,
                width=72,
            )
            status.grid(row=0, column=5, padx=4)

    def _toggle_config2(self) -> None:
        self.ctrl.append_log("Telegram → Config #2")
        self._show_config2(True)

    def _show_config2(self, show: bool) -> None:
        if self._config2_frame is None:
            return
        tabview = self._config2_frame.master
        if show and hasattr(tabview, "set"):
            tabview.set("Config #2")

    def _save_appearance(self) -> None:
        self.ctrl.save_config_from_ui(
            {
                "appearance_mode": self._vars["appearance_mode"].get(),
                "gui_scaling": self._vars["gui_scaling"].get(),
            }
        )

    def _save_config1(self) -> None:
        sens_raw = self._vars["cs2_sensitivity"].get().strip()
        try:
            cs2_sensitivity = float(sens_raw) if sens_raw else 2.1
        except ValueError:
            cs2_sensitivity = 2.1
            self.ctrl.append_log("WARN: invalid cs2_sensitivity — saved as 2.1")
        self.ctrl.save_config_from_ui(
            {
                "trade_offer_link": self._vars["trade_offer_link"].get().strip(),
                "cs2_sensitivity": cs2_sensitivity,
                "auto_collect_drop": bool(self._vars["auto_collect_drop"].get()),
                "start_farm_when_launched": bool(
                    self._vars["start_farm_when_launched"].get()
                ),
                "only_launch_steam": bool(self._vars["only_launch_steam"].get()),
                "steam_auto_login": bool(self._vars["steam_auto_login"].get()),
                "steam_kill_before_login": bool(
                    self._vars["steam_kill_before_login"].get()
                ),
                "steam_login_mode": self._vars["steam_login_mode"].get().strip(),
            }
        )

    def _save_config2(self) -> None:
        raw_timer = self._vars["autofarm_timer_minutes"].get().strip()
        self.ctrl.save_config_from_ui(
            {
                "telegram_bot_token": self._vars["telegram_bot_token"].get().strip(),
                "telegram_chat_id": self._vars["telegram_chat_id"].get().strip(),
                "telegram_send_screenshot": bool(
                    self._vars["telegram_send_screenshot"].get()
                ),
                "autofarm_timer_minutes": int(raw_timer or "70"),
            }
        )

    def _save_config3(self) -> None:
        self.ctrl.save_config_from_ui(
            {
                "cooldown_between_accounts_sec": int(
                    self._vars["cooldown_between_accounts_sec"].get() or "0"
                ),
                "max_dm_minutes": int(self._vars["max_dm_minutes"].get() or "90"),
                "cs2_fps_limit_nvidia": int(
                    self._vars["cs2_fps_limit_nvidia"].get() or "0"
                ),
                "proxy_expected_ip": self._vars["proxy_expected_ip"].get().strip(),
                "steam_classic_login_ui": bool(
                    self._vars["steam_classic_login_ui"].get()
                ),
                "fsm_logpass_path": self._vars["fsm_logpass_path"].get().strip(),
                "fsm_mafiles_dir": self._vars["fsm_mafiles_dir"].get().strip(),
                "bot_mode": BotMode(self._vars["bot_mode"].get()),
                "csgobot_require_cuda": bool(
                    self._vars["csgobot_require_cuda"].get()
                ),
                "csgobot_nav_enabled": bool(
                    self._vars["csgobot_nav_enabled"].get()
                ),
                "csgobot_nav_pack": self._vars["csgobot_nav_pack"].get().strip()
                or "dust2_dm",
                "nav_fleet_push_url": self._vars["nav_fleet_push_url"].get().strip(),
                "nav_fleet_collector_port": int(
                    self._vars["nav_fleet_collector_port"].get() or "8765"
                ),
                "nav_fleet_collector_token": self._vars[
                    "nav_fleet_collector_token"
                ].get().strip(),
            }
        )

    def refresh_counters(self) -> None:
        if self._counters_label is None:
            return
        self._counters_label.configure(
            text=(
                f"Selected: {self.ctrl.selected_count} | "
                f"Launched: {self.ctrl.launched_count} | "
                f"Farmed: {self.ctrl.farmed_count}"
            )
        )

    def _on_start_farm(self) -> None:
        self.ctrl.start_farm()

    def _on_start_selected(self) -> None:
        self.ctrl.start_selected()

    def _on_launch_selected(self) -> None:
        self.ctrl.launch_selected()

    def _on_get_lvl(self) -> None:
        self.ctrl.get_lvl_selected()

    def on_close(self) -> None:
        w, h = self.root.winfo_width(), self.root.winfo_height()
        self.ctrl.save_config_from_ui({"panel_geometry": f"{w}x{h}"})
