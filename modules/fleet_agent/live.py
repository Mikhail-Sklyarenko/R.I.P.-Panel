"""Windows GameBackend: observe Steam/CS2, run one bounded UI command, admit gameplay.

UI automation and the combat worker never own the keyboard at the same time.
Unknown screens, missing calibration and account mismatch refuse the command.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

from core.startup_checks import APP_VERSION
from core.wingman_fleet import PROTOCOL_VERSION
from core.wingman_fleet.models import (
    Command, CommandResult, CommandType, GsiView, Identity, LobbyView, Observation, ResultStatus, Screen,
)
from core.wingman_fleet.reasons import Reason
from core.wingman_fleet.roster import resource_manifest_hash
from modules.fleet_agent.backend import ExecContext
from modules.fleet_agent.gsi import FleetGsi, install, load_token
from modules.fleet_agent.identity import IdentityProbe
from modules.fleet_agent.input_supervisor import InputBusy, InputSupervisor
from modules.fleet_agent.match_status import fingerprint_from_names, parse_status
from modules.fleet_agent.observe import MenuObserver, ScreenEvidence
from modules.fleet_agent.preflight import (
    Preflight, check_cs2_client_size, check_inferno_pack, check_virtual_camera,
    check_worker_installed, check_worker_preflight,
)
from modules.fleet_agent.processes import cs2_running, steam_running

_log = logging.getLogger(__name__)
LEASE_TTL_SEC = 1.5
CAPTURE_STALE_SEC = 2.0


def default_manifest() -> str:
    from config.paths import get_app_root
    root = get_app_root()
    return resource_manifest_hash([
        root / "resources" / "wingman" / "inferno",
        root / "resources" / "nav" / "packs" / "inferno_visual.yaml",
        root / "resources" / "wingman" / "hud_ru_1280",
        root / "resources" / "ui_nav" / "wingman_fleet.yaml",
        root / "vendor" / "csgobot" / "fleet_gate.py",
    ])


class WindowsBackend:
    def __init__(self, *, agent_id: str, expected_steam_id64: str = "", computer: str = "",
                 log: Callable[[str], None] | None = None, capture=None, clock=time.monotonic):
        from config.loader import load_config
        from config.paths import get_data_dir, get_logs_dir
        self.agent_id = agent_id
        self.expected = expected_steam_id64
        self.computer = computer
        self.log = log or (lambda m: _log.info("%s", m))
        self.clock = clock
        self.config = load_config()
        self.identity = IdentityProbe()
        self.observer = MenuObserver()
        self.inputs = InputSupervisor()
        self.gsi: FleetGsi | None = None
        self._capture = capture
        self._lock = threading.RLock()
        self._lease = ""
        self._lease_generation = 0
        self._worker_exit = ""
        self._last_screen = Screen.UNKNOWN
        self._screen_since = clock()
        self._last_capture = 0.0
        self._last_fp = None
        self._friends: frozenset[str] = frozenset()
        self._lobby = LobbyView()
        self._invite_from = ""
        self._modal = ""
        self.data = get_data_dir() / "fleet_agent"
        self.data.mkdir(parents=True, exist_ok=True)
        self.admission = self.data / "admission.json"
        self.stop_file = self.data / "worker.stop"
        self.shots = get_logs_dir() / "fleet" / agent_id
        self.shots.mkdir(parents=True, exist_ok=True)
        self.preflight = Preflight([
            ("steam", lambda: (steam_running(), ""), 1.0),
            ("cs2", lambda: (cs2_running(), ""), 1.0),
            ("identity", self._check_identity, 1.0),
            ("resolution", check_cs2_client_size, 5.0),
            ("worker", check_worker_installed, 60.0),
            ("csgobot", check_worker_preflight, 120.0),
            ("nav", check_inferno_pack, 120.0),
            ("camera", check_virtual_camera, 15.0),
            ("gsi", self._check_gsi, 0),
            ("observer", lambda: (self.observer.calibrated, "wingman_fleet.yaml"), 30.0),
            ("input", lambda: (True, self.inputs.describe()), 0),
        ], clock=clock)
        self._install_gsi()

    def _install_gsi(self) -> None:
        try:
            from modules.launcher.cs2 import find_csgo_cfg_dir, resolve_cs2_exe
            token = load_token()
            cfg_dir = find_csgo_cfg_dir(resolve_cs2_exe(self.config))
            _, changed = install(cfg_dir, token)
            self.gsi = FleetGsi(token).start()
            if changed:
                self.log("fleet: GSI cfg written — restart CS2 once")
        except Exception as exc:
            self.log(f"fleet: GSI not installed ({exc})")

    def _check_identity(self) -> tuple[bool, str]:
        found = self.identity.probe(
            gsi_steam_id64=self.gsi.view().steam_id64 if self.gsi else "",
            gsi_fresh=bool(self.gsi and self.gsi.view().fresh),
            expected_steam_id64=self.expected,
        )
        return found.identity is not Identity.MISMATCH and found.identity is not Identity.UNCONFIRMED, found.detail

    def _check_gsi(self) -> tuple[bool, str]:
        if self.gsi is None:
            return False, "receiver not started"
        view = self.gsi.view()
        if view.age_sec == float("inf"):
            return False, "no packets yet (restart CS2 after GSI install)"
        if not view.fresh:
            return False, f"stale age={view.age_sec:.1f}s"
        return True, f"age={view.age_sec:.1f}s"

    def close(self) -> None:
        self.safe_stop("backend close")
        if self.gsi is not None:
            self.gsi.close()
            self.gsi = None

    # ----- observation ---------------------------------------------------------------
    def observe(self) -> Observation:
        steam, cs2 = steam_running(), cs2_running()
        gsi = self.gsi.view() if self.gsi else GsiView()
        found = self.identity.probe(gsi_steam_id64=gsi.steam_id64, gsi_fresh=gsi.fresh,
                                    expected_steam_id64=self.expected)
        image = None
        capture_age = float("inf")
        try:
            image = self._grab()
            if image is not None:
                self._last_capture = self.clock()
                capture_age = 0.0
        except Exception as exc:
            self.log(f"fleet: capture failed: {exc}")
        if self._last_capture:
            capture_age = self.clock() - self._last_capture
        ev = self.observer.classify(
            image, gsi_mode=gsi.mode, gsi_map=gsi.map_id, gsi_phase=gsi.map_phase,
            gsi_fresh=gsi.fresh, steam_running=steam, cs2_running=cs2,
        )
        if ev.state is not self._last_screen:
            self._last_screen, self._screen_since = ev.state, self.clock()
        self._modal = ev.blocking_modal
        # No lobby sensor yet. A remembered or clicked roster is not an observation.
        self._lobby = LobbyView()
        results = self.preflight.refresh_for_observation()
        ok, failures = Preflight.summary(results)
        fp = None
        if ev.state is Screen.IN_MATCH and gsi.fresh:
            names = self.gsi.roster_names() if self.gsi else ()
            token = self.gsi.server_token() if self.gsi else ""
            fresh_fp = fingerprint_from_names(token, names, observed_age_sec=gsi.age_sec)
            if fresh_fp is not None and fresh_fp.observed_age_sec <= 2.0:
                self._last_fp = fresh_fp
                fp = fresh_fp
        else:
            self._last_fp = None
        from modules.combat import csgobot_ai
        worker = csgobot_ai._PROCESS is not None and csgobot_ai._PROCESS.poll() is None
        return Observation(
            agent_id=self.agent_id, sequence=0, protocol=PROTOCOL_VERSION,
            build_version=APP_VERSION, resource_manifest=default_manifest(),
            steam_running=steam, cs2_running=cs2, steam_id64=found.steam_id64,
            identity=found.identity, screen=ev.state, screen_confidence=ev.confidence,
            screen_stable_sec=self.clock() - self._screen_since, modal=self._modal,
            lobby=self._lobby, invite_from=self._invite_from, friends=self._friends,
            gsi=gsi, fingerprint=fp, capture_age_sec=capture_age,
            input_owner=self.inputs.describe(), worker_running=worker,
            worker_exit=self._worker_exit, preflight_ok=ok, preflight_failures=failures,
        )

    def _grab(self):
        if self._capture is not None:
            return self._capture()
        import sys
        if sys.platform != "win32":
            return None
        from modules.ui_nav.capture import capture_client
        from modules.ui_nav.window import find_cs2_hwnd
        try:
            hwnd = find_cs2_hwnd()
        except Exception:
            return None
        return capture_client(hwnd, skip_focus=True)

    def _shot(self, tag: str, image=None) -> str:
        try:
            from datetime import datetime, timezone
            img = image if image is not None else self._grab()
            if img is None:
                return ""
            path = self.shots / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{tag}.png"
            img.save(path)
            self._rotate_shots()
            return str(path)
        except Exception:
            return ""

    def _rotate_shots(self, keep: int = 40) -> None:
        files = sorted(self.shots.glob("*.png"), key=lambda p: p.stat().st_mtime)
        for old in files[:-keep]:
            try:
                old.unlink()
            except OSError:
                pass

    # ----- lease / worker ------------------------------------------------------------
    def set_gameplay(self, attempt_id: str, generation: int = 0) -> None:
        with self._lock:
            current = getattr(self, "_lease_generation", 0)
            if generation > 0 and generation < current:
                return
            if generation > 0:
                self._lease_generation = generation
            self._lease = attempt_id
            if attempt_id:
                if not self.inputs.grant_gameplay(attempt_id):
                    self.log("fleet: gameplay lease refused — UI still owns inputs")
                    return
                self.admission.write_text(json.dumps({
                    "attempt_id": attempt_id, "expires_at": time.time() + LEASE_TTL_SEC,
                }), encoding="utf-8")
            else:
                self.inputs.revoke_gameplay()
                if self.admission.is_file():
                    self.admission.write_text(json.dumps({
                        "attempt_id": "", "expires_at": 0,
                    }), encoding="utf-8")
                from modules.combat import csgobot_ai
                if csgobot_ai._PROCESS is not None:
                    csgobot_ai.stop_ai()

    def safe_stop(self, reason: str) -> None:
        self.log(f"fleet: safe_stop ({reason})")
        self._last_fp = None
        self.stop_file.write_text(reason, encoding="utf-8")
        self.set_gameplay("")
        self.inputs.release_all()
        try:
            from modules.combat import csgobot_ai
            csgobot_ai.stop_ai()
        except Exception:
            _log.exception("stop_ai")
        try:
            from modules.ui_nav.actions import release_all_inputs
            release_all_inputs()
        except Exception:
            pass

    # ----- commands ------------------------------------------------------------------
    def execute(self, cmd: Command, ctx: ExecContext) -> CommandResult:
        if ctx.cancel.is_set() and cmd.type not in (CommandType.SAFE_STOP, CommandType.STOP_GAMEPLAY):
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.OPERATOR_STOP.value, "cancelled")
        if cmd.type is CommandType.START_GAMEPLAY:
            return self._start_gameplay(cmd, ctx)
        if cmd.type is CommandType.STOP_GAMEPLAY:
            self.set_gameplay("")
            return CommandResult(cmd.command_id, ResultStatus.COMPLETED)
        if cmd.type is CommandType.SAFE_STOP:
            self.safe_stop("command")
            return CommandResult(cmd.command_id, ResultStatus.COMPLETED)
        if cmd.type is CommandType.PREFLIGHT:
            ok, failures = Preflight.summary(self.preflight.run(force=True))
            return CommandResult(cmd.command_id,
                                 ResultStatus.COMPLETED if ok else ResultStatus.FAILED,
                                 "" if ok else Reason.PREFLIGHT_FAILED.value, "; ".join(failures))
        if cmd.type is CommandType.PROBE_MATCH:
            return self._probe(cmd)
        if cmd.type is CommandType.SCREENSHOT:
            path = self._shot("operator")
            if not path:
                return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.CAPTURE_STALE.value, "no image")
            return CommandResult(cmd.command_id, ResultStatus.COMPLETED, "", path)
        if cmd.type is CommandType.RESTART_CS2:
            return self._restart(cmd, ctx, steam=False)
        if cmd.type is CommandType.RESTART_STEAM:
            return self._restart(cmd, ctx, steam=True)
        return self._ui(cmd, ctx)

    def _start_gameplay(self, cmd: Command, ctx: ExecContext) -> CommandResult:
        attempt = str(cmd.params.get("attempt_id", ""))
        if not attempt or ctx.gameplay_attempt() != attempt:
            return CommandResult(cmd.command_id, ResultStatus.REJECTED, Reason.GAMEPLAY_NOT_ADMITTED.value,
                                 f"lease={ctx.gameplay_attempt()!r}")
        obs = self.observe()
        if obs.identity is Identity.MISMATCH:
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.ACCOUNT_MISMATCH.value, obs.steam_id64)
        if obs.screen is not Screen.IN_MATCH or not obs.gsi.fresh:
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.GAMEPLAY_NOT_ADMITTED.value,
                                 obs.screen.value)
        if obs.gsi.map_id != "de_inferno" or obs.gsi.mode != "scrimcomp2v2":
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.MATCH_MISMATCH.value,
                                 f"{obs.gsi.mode}/{obs.gsi.map_id}")
        from modules.combat import csgobot_ai
        from modules.wingman.setup import prepare
        path, changed = prepare(self.config)
        if changed:
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.PREFLIGHT_FAILED.value,
                                 "GSI cfg changed — restart CS2")
        self.stop_file.unlink(missing_ok=True)
        self.set_gameplay(attempt)
        ctx_ai = {
            "config": self.config, "login": self.agent_id, "session_id": f"fleet-{self.agent_id}",
            "wingman_gsi_path": str(path), "fleet_admission_file": str(self.admission),
            "fleet_stop_file": str(self.stop_file), "fleet_attempt_id": attempt,
            "stop_requested": False, "emit": lambda *a, **k: None,
        }
        ok = csgobot_ai.start_ai(ctx_ai)
        if not ok:
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.WORKER_FAILED.value, "start_ai")
        self._worker_exit = ""
        return CommandResult(cmd.command_id, ResultStatus.COMPLETED, "", attempt)

    def _probe(self, cmd: Command) -> CommandResult:
        obs = self.observe()
        fp = obs.fingerprint
        dump = self.data / "status.txt"
        if fp is None and dump.is_file():
            fp = parse_status(dump.read_text(encoding="utf-8", errors="replace"))
        if fp is None or not fp.players:
            shot = self._shot("probe")
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.MATCH_PROOF_UNAVAILABLE.value,
                                 "no roster", {"screenshot": shot})
        self._last_fp = fp
        return CommandResult(cmd.command_id, ResultStatus.COMPLETED, "", fp.server_token,
                             {"players": list(fp.players), "server": fp.server_token})

    def _restart(self, cmd: Command, ctx: ExecContext, *, steam: bool) -> CommandResult:
        self.safe_stop("restart")
        if ctx.cancel.is_set():
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.OPERATOR_STOP.value, "cancelled")
        try:
            from modules.launcher import cleanup, cs2, steam as steam_mod
            if steam:
                cleanup.kill_all()
                steam_mod.launch_steam(self.config)
            else:
                cleanup.kill_cs2()
            cs2.launch_cs2(self.config)
        except Exception as exc:
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.COMMAND_FAILED.value, repr(exc))
        deadline = self.clock() + 90.0
        while self.clock() < deadline:
            if ctx.cancel.is_set():
                return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.OPERATOR_STOP.value, "cancelled")
            if steam_running() and cs2_running():
                return CommandResult(cmd.command_id, ResultStatus.COMPLETED)
            time.sleep(1.0)
        if ctx.cancel.is_set():
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.OPERATOR_STOP.value, "cancelled")
        return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.CS2_NOT_RUNNING.value, "timeout")

    def _ui(self, cmd: Command, ctx: ExecContext) -> CommandResult:
        if not self.observer.calibrated:
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.CALIBRATION_MISSING.value,
                                 "wingman_fleet.yaml")
        obs = self.observe()
        if obs.identity is Identity.MISMATCH:
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.ACCOUNT_MISMATCH.value, obs.steam_id64)
        if obs.screen is Screen.UNKNOWN:
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.UNKNOWN_SCREEN.value,
                                 self._shot(cmd.type.value))
        if cmd.type is CommandType.SEND_FRIEND_REQUEST:
            target = str(cmd.params.get("steam_id64", ""))
            if target and target in self._friends:
                return CommandResult(cmd.command_id, ResultStatus.ALREADY_APPLIED)
            code = str(cmd.params.get("friend_code", ""))
            result = self._click_seq(cmd, ctx, ["add_friend", "friend_code_field", "send_friend"],
                                     paste=code)
            if result.succeeded and target:
                self._friends = frozenset(self._friends | {target})
            return result
        if cmd.type is CommandType.LEAVE_LOBBY:
            return self._click_seq(cmd, ctx, ["leave_lobby"])
        if cmd.type is CommandType.CONFIGURE_LOBBY:
            return self._click_seq(cmd, ctx, ["play", "mode_wingman", "map_inferno"])
        if cmd.type is CommandType.INVITE:
            if cmd.params.get("replace_stale"):
                self._invite_from = ""
            return self._click_seq(cmd, ctx, ["invite_open", "invite_first"])
        if cmd.type is CommandType.ACCEPT_INVITE:
            self._invite_from = str(cmd.params.get("steam_id64", ""))
            return self._click_seq(cmd, ctx, ["accept_invite"])
        if cmd.type is CommandType.START_SEARCH:
            start_at = float(cmd.params.get("start_at_coordinator", 0) or 0)
            while start_at and ctx.coordinator_time() < start_at - 0.02:
                if ctx.cancel.is_set():
                    return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.OPERATOR_STOP.value)
                time.sleep(0.02)
            return self._click_seq(cmd, ctx, ["start_search"])
        if cmd.type is CommandType.CANCEL_SEARCH:
            return self._click_seq(cmd, ctx, ["cancel_search"])
        if cmd.type is CommandType.ACCEPT_MATCH:
            return self._click_seq(cmd, ctx, ["accept_match"])
        if cmd.type is CommandType.LEAVE_MATCH:
            return self._console_or_click(cmd, ctx, "disconnect", ["leave_lobby"])
        if cmd.type is CommandType.RETURN_TO_MENU:
            return self._console_or_click(cmd, ctx, "disconnect", ["leave_lobby"])
        if cmd.type is CommandType.RECONNECT_MATCH:
            return self._console_or_click(cmd, ctx, "retry", ["play"])
        return CommandResult(cmd.command_id, ResultStatus.REJECTED, Reason.COMMAND_FAILED.value, cmd.type.value)

    def _click_seq(self, cmd: Command, ctx: ExecContext, names: list[str], *, paste: str = "") -> CommandResult:
        try:
            from modules.ui_nav.actions import click_client, paste_text
            from modules.ui_nav.coords import Point
            from modules.ui_nav.window import find_cs2_hwnd
        except Exception as exc:
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.COMMAND_FAILED.value, repr(exc))
        try:
            hwnd = find_cs2_hwnd()
        except Exception as exc:
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.CS2_NOT_RUNNING.value, str(exc))
        try:
            with self.inputs.ui(cmd.type.value):
                for name in names:
                    if ctx.cancel.is_set():
                        return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.OPERATOR_STOP.value)
                    pt = self.observer.click_point(name)
                    if pt is None:
                        return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.CALIBRATION_MISSING.value, name)
                    click_client(hwnd, Point(*pt))
                    time.sleep(0.25)
                    if paste and name.endswith("field"):
                        paste_text(hwnd, paste)
                        paste = ""
                        time.sleep(0.2)
        except InputBusy as exc:
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.INPUT_BUSY.value, str(exc))
        except Exception as exc:
            self._shot(cmd.type.value)
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.COMMAND_FAILED.value, repr(exc))
        self._shot(f"{cmd.type.value}_after")
        return CommandResult(cmd.command_id, ResultStatus.UNCONFIRMED, Reason.EFFECT_UNCONFIRMED.value,
                             "clicks issued; effect not observed")

    def _console_or_click(self, cmd: Command, ctx: ExecContext, console: str, clicks: list[str]) -> CommandResult:
        if ctx.cancel.is_set():
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.OPERATOR_STOP.value, "cancelled")
        try:
            from modules.ui_nav.cs2_console import run_cs2_console_commands
            from modules.ui_nav.window import find_cs2_hwnd
            with self.inputs.ui(cmd.type.value):
                run_cs2_console_commands(find_cs2_hwnd(), console)
        except Exception:
            if ctx.cancel.is_set():
                return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.OPERATOR_STOP.value, "cancelled")
            return self._click_seq(cmd, ctx, clicks)
        if ctx.cancel.is_set():
            return CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.OPERATOR_STOP.value, "cancelled")
        return CommandResult(cmd.command_id, ResultStatus.UNCONFIRMED, Reason.EFFECT_UNCONFIRMED.value, console)
