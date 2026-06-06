"""Полная цепочка сессии до DONE; real hooks → NotImplementedError."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Callable

from core.event_log import append_event
from core.events import EventType
from core.fsm import apply_event
from config.loader import load_config
from core.session_mode import SessionMode
from core.session_state import InvalidTransitionError, SessionState, advance
from modules._fakes.timing import reset_step_budget


@dataclass
class SessionContext:
    login: str
    test_mode: bool
    on_main: Callable[[str], None] | None = None
    on_drop: Callable[[str], None] | None = None
    session_id: str = ""
    state: SessionState = field(default=SessionState.QUEUED)
    session_mode: SessionMode = SessionMode.FULL
    force_farm: bool = False
    early_launch_wait: bool = False
    only_launch_steam: bool = False
    cs2_hwnd: int | None = None
    cs2_menu_probe_warn: bool = False

    def emit(
        self,
        event: EventType,
        detail: str = "",
        *,
        drop_log: bool = False,
    ) -> None:
        prev = self.state
        try:
            self.state = apply_event(self.state, event)
        except InvalidTransitionError:
            if event not in (
                EventType.COMBAT_AI_STARTED,
                EventType.COMBAT_STOPPED,
                EventType.COMBAT_FALLBACK,
                EventType.FARMING,
                EventType.IDLE,
                EventType.IP_OK,
                EventType.STEAM_LOGIN_START,
                EventType.STEAM_LOGIN_OK,
                EventType.STEAM_LOGIN_FAILED,
            ):
                self.state = apply_event(self.state, EventType.SESSION_FAILED)
                detail = detail or str(event.value)
                append_event(
                    EventType.SESSION_FAILED,
                    login=self.login,
                    state=self.state,
                    detail=detail,
                )
                self._ui_main(f"[{self.login}] session_failed: invalid transition")
                return

        append_event(event, login=self.login, state=self.state, detail=detail or None)
        msg = f"[{self.login}] {event.value}"
        if self.state != prev:
            msg += f" → {self.state.value}"
        if detail:
            msg += f" ({detail})"
        self._ui_main(msg)
        if drop_log:
            self._ui_drop(f"[{self.login}] {detail or event.value}")

    def _ui_main(self, line: str) -> None:
        if self.on_main:
            self.on_main(line)

    def _ui_drop(self, line: str) -> None:
        if self.on_drop:
            self.on_drop(line)


def _hook_launcher(ctx: SessionContext) -> bool:
    if ctx.test_mode:
        from modules._fakes import launcher as fake

        fake.run(ctx)
        return ctx.state != SessionState.FAILED

    from modules import launcher

    run_ctx: dict = {
        "login": ctx.login,
        "emit": ctx.emit,
        "session_id": ctx.session_id,
        "config": load_config(),
        "on_login_progress": lambda msg: ctx._ui_main(f"[{ctx.login}] {msg}"),
        "on_cs2_progress": lambda msg: ctx._ui_main(f"[{ctx.login}] {msg}"),
    }
    ok = launcher.run(run_ctx)
    if not ok:
        return False
    ctx.cs2_hwnd = run_ctx.get("cs2_hwnd")
    ctx.cs2_menu_probe_warn = bool(run_ctx.get("cs2_menu_probe_warn"))
    if run_ctx.get("stop_after_steam"):
        ctx.only_launch_steam = True
        ctx.state = advance(ctx.state, SessionState.CLEANUP)
        ctx.emit(EventType.EXITED, "only_launch_steam: skip CS2/DM")
        return True
    config = load_config()
    if (
        ctx.session_mode is SessionMode.FULL
        and not config.start_farm_when_launched
        and not ctx.force_farm
    ):
        ctx.early_launch_wait = True
        ctx.state = advance(ctx.state, SessionState.CLEANUP)
        ctx.emit(
            EventType.IN_MENU,
            "start_farm_when_launched=false: waiting for Start Farm",
        )
        return True
    return ctx.state != SessionState.FAILED


def _dm_ctx(ctx: SessionContext) -> dict:
    dm: dict = {
        "login": ctx.login,
        "emit": ctx.emit,
        "session_id": ctx.session_id,
        "config": load_config(),
        "on_nav_progress": lambda msg: ctx._ui_main(f"[{ctx.login}] {msg}"),
    }
    if ctx.cs2_hwnd:
        dm["hwnd"] = ctx.cs2_hwnd
    if ctx.cs2_menu_probe_warn:
        dm["cs2_menu_probe_warn"] = True
    return dm


def _hook_dm_to_match(ctx: SessionContext) -> bool:
    if ctx.test_mode:
        from modules._fakes import dm_runner as fake

        fake.run_to_dm(ctx)
        return ctx.state != SessionState.FAILED
    from modules import dm_runner

    return dm_runner.run(_dm_ctx(ctx))


def _hook_combat(ctx: SessionContext) -> bool:
    from modules.combat import run_combat_phase

    run_ctx = _dm_ctx(ctx)
    if ctx.test_mode:
        import os

        os.environ.setdefault("LEVEL_DETECT_SIM", "1")
        os.environ.setdefault("LEVEL_DETECT_AFTER_SEC", "0.5")
    result = run_combat_phase(run_ctx)
    if not result.get("ok", False):
        return False
    if result.get("outcome") == "combat_timeout":
        return ctx.state == SessionState.CLEANUP
    return ctx.state in (SessionState.LEVEL_UP, SessionState.FARMING)


def _hook_drop_and_loot(ctx: SessionContext) -> bool:
    if ctx.test_mode:
        from modules._fakes import drop_picker as fake_drop
        from modules._fakes import looter as fake_loot

        fake_drop.run(ctx)
        if ctx.state == SessionState.FAILED:
            return False
        fake_loot.run(ctx)
        return ctx.state != SessionState.FAILED
    from modules import drop_picker, looter

    try:
        drop_picker.pick(_dm_ctx(ctx))
        looter.send_trade(_dm_ctx(ctx))
    except NotImplementedError as exc:
        ctx.emit(EventType.SESSION_FAILED, f"loot pipeline: {exc}")
        return False
    return True


def _hook_cleanup(ctx: SessionContext) -> bool:
    if ctx.test_mode:
        from modules._fakes import dm_runner as fake

        if ctx.session_mode is not SessionMode.LAUNCH_ONLY:
            fake.run_exit(ctx)
        ctx.emit(
            EventType.EXITED,
            "cleanup (fake)"
            if ctx.session_mode is SessionMode.LAUNCH_ONLY
            else "cleanup (fake)",
        )
        return ctx.state != SessionState.FAILED

    from modules import dm_runner
    from modules.launcher import run_cleanup

    try:
        if ctx.session_mode is SessionMode.LAUNCH_ONLY:
            ctx.emit(EventType.EXITED, "launch_only: keep steam/cs2 running")
            return True
        if ctx.only_launch_steam:
            run_cleanup(kill_steam=False, kill_cs2=True, stop_auth=True)
            ctx.emit(EventType.EXITED, "only_launch_steam: cleanup (steam kept)")
            return True
        if ctx.state not in (SessionState.QUEUED, SessionState.LAUNCHING):
            dm_runner.run_exit(_dm_ctx(ctx))
        killed = run_cleanup(kill_steam=True, kill_cs2=True, stop_auth=True)
        ctx.emit(EventType.EXITED, f"cleanup: {killed}")
    except Exception as exc:
        ctx.emit(EventType.SESSION_FAILED, f"cleanup: {exc}")
        return False
    return True


def run_session(
    login: str,
    *,
    test_mode: bool,
    session_mode: SessionMode = SessionMode.FULL,
    force_farm: bool = False,
    on_main: Callable[[str], None] | None = None,
    on_drop: Callable[[str], None] | None = None,
) -> SessionState:
    """Happy-path до DROP_PICKING, LOOTING, CLEANUP, DONE (fakes ~20s)."""
    if test_mode:
        reset_step_budget(16)

    ctx = SessionContext(
        login=login,
        test_mode=test_mode,
        on_main=on_main,
        on_drop=on_drop,
        session_id=uuid.uuid4().hex[:12],
        session_mode=session_mode,
        force_farm=force_farm,
    )
    ctx.emit(
        EventType.SESSION_START,
        f"session_fsm: start ({session_mode.value})",
    )

    if session_mode is SessionMode.LAUNCH_ONLY:
        hooks = (_hook_launcher, _hook_cleanup)
    else:
        hooks = (
            _hook_launcher,
            _hook_dm_to_match,
            _hook_combat,
            _hook_drop_and_loot,
            _hook_cleanup,
        )
    for hook in hooks:
        if ctx.state in (SessionState.FAILED, SessionState.DONE):
            break
        if ctx.state == SessionState.CLEANUP and hook in (
            _hook_dm_to_match,
            _hook_combat,
            _hook_drop_and_loot,
        ):
            continue
        if ctx.state == SessionState.LEVEL_UP and hook == _hook_combat:
            continue
        if not hook(ctx):
            break

    if ctx.early_launch_wait:
        ctx.emit(EventType.EXITED, "launch wait — use Start Farm to continue")
    elif ctx.state == SessionState.CLEANUP:
        ctx.emit(EventType.SESSION_DONE, "session_fsm: complete")
    elif ctx.state not in (SessionState.DONE, SessionState.FAILED):
        ctx.emit(EventType.SESSION_FAILED, "session_fsm: incomplete pipeline")

    if ctx.state == SessionState.DONE and on_main:
        on_main(f"[{login}] DONE")

    return ctx.state
