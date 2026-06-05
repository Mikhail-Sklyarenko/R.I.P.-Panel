"""Конвейер: unfarmed → orchestrator → farmed_this_week (B10)."""

from __future__ import annotations

from collections.abc import Callable

from config.loader import load_config
from core.orchestrator import Orchestrator
from core.session_mode import SessionMode
from core.session_state import SessionState
from modules.vault.store import list_unfarmed_logins, mark_farmed_this_week


def build_queue(
    *,
    selected: list[str] | None = None,
    only_unfarmed: bool = True,
) -> list[str]:
    """
    Очередь логинов.
    selected задан → только выбранные (опционально без уже farmed).
    иначе → все unfarmed из vault.
    """
    unfarmed = set(list_unfarmed_logins())
    if selected:
        logins = [s.strip() for s in selected if s.strip()]
        if only_unfarmed:
            logins = [login for login in logins if login in unfarmed]
        return logins
    return list_unfarmed_logins()


def run_conveyor(
    logins: list[str] | None = None,
    *,
    test_mode: bool | None = None,
    session_mode: SessionMode = SessionMode.FULL,
    force_farm: bool = False,
    on_log: Callable[[str], None] | None = None,
    on_drop: Callable[[str], None] | None = None,
    timeout_sec: float = 3600.0,
) -> bool:
    """
    Headless конвейер (без UI). Возвращает True если очередь отработана.
    """
    cfg = load_config()
    tm = cfg.test_mode if test_mode is None else test_mode
    queue = logins if logins is not None else build_queue()
    log = on_log or (lambda _m: None)

    if not queue:
        log("conveyor: no accounts to run")
        return True

    log(f"conveyor: queue {len(queue)} — {', '.join(queue)}")

    def _on_complete(
        login: str, final: SessionState, mode: SessionMode
    ) -> None:
        if final is SessionState.DONE and mode is SessionMode.FULL:
            mark_farmed_this_week(login)
            log(f"conveyor: {login} farmed_this_week=true")

    orch = Orchestrator(
        test_mode=tm,
        ui_callback=log,
        drop_callback=on_drop or (lambda _m: None),
        on_session_complete=_on_complete,
    )
    orch.enqueue(queue, mode=session_mode, force_farm=force_farm)
    ok = orch.wait_until_idle(timeout=timeout_sec)
    if ok:
        log("conveyor: finished")
    else:
        log("conveyor: timeout or incomplete queue")
    return ok


def run_night_conveyor(
    *,
    max_accounts: int = 3,
    test_mode: bool | None = None,
    on_log: Callable[[str], None] | None = None,
) -> bool:
    """Критерий B10: N acc подряд без UI (обычно test_mode + fakes)."""
    queue = build_queue()[:max_accounts]
    return run_conveyor(
        queue,
        test_mode=test_mode,
        on_log=on_log,
        timeout_sec=600.0,
    )
