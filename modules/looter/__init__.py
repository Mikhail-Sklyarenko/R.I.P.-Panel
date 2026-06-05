"""Looter: Node subprocess vendor/looter/looter_core.js → trade на storage."""

from __future__ import annotations

from typing import Any, Protocol

from config.loader import load_config
from config.schema import AppConfig
from core.events import EventType
from modules.looter.runner import (
    DEFAULT_INVENTORY,
    detail_from_result,
    looter_script_path,
    run_looter_core,
)
from modules.vault.store import AccountNotFoundError, load_account


class _Emit(Protocol):
    def __call__(
        self,
        event: EventType,
        detail: str = "",
        *,
        drop_log: bool = False,
    ) -> None: ...


def send_trade(ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    CLI как FSM: node looter_core.js login pass shared identity trade [730/2].
    exit code 1 → loot_ok; иначе loot_failed.
    auto_collect_drop=false → skip (без subprocess).
    """
    if ctx is None:
        ctx = {}
    config: AppConfig | None = ctx.get("config")
    if config is None:
        config = load_config()
        ctx["config"] = config

    emit: _Emit | None = ctx.get("emit")
    login = str(ctx.get("login", "")).strip()
    if not login:
        _emit_failed(emit, "looter: login required")
        return {"ok": False, "error": "login required"}

    if not config.auto_collect_drop:
        detail = "skipped: auto_collect_drop=false"
        if emit:
            emit(EventType.LOOT_OK, detail, drop_log=True)
        return {"ok": True, "skipped": True, "detail": detail}

    trade_link = (config.trade_offer_link or "").strip()
    if not trade_link:
        _emit_failed(emit, "looter: trade_offer_link empty")
        return {"ok": False, "error": "trade_offer_link empty"}

    try:
        secrets = load_account(login)
    except AccountNotFoundError as exc:
        _emit_failed(emit, f"looter: {exc}")
        return {"ok": False, "error": str(exc)}

    inventory = str(ctx.get("inventory", DEFAULT_INVENTORY))
    script = looter_script_path()
    try:
        result = run_looter_core(
            login=secrets["login"],
            password=secrets["password"],
            shared_secret=secrets["shared_secret"],
            identity_secret=secrets["identity_secret"],
            trade_offer_link=trade_link,
            inventory=inventory,
        )
    except Exception as exc:
        _emit_failed(emit, f"looter: {exc}")
        return {"ok": False, "error": str(exc)}

    detail = f"{script.as_posix()} | {detail_from_result(result)}"
    if result.exit_code == 1:
        if emit:
            emit(EventType.LOOT_OK, detail, drop_log=True)
        return {"ok": True, "exit_code": result.exit_code, "detail": detail}

    _emit_failed(emit, detail)
    return {
        "ok": False,
        "exit_code": result.exit_code,
        "detail": detail,
        "error": f"unexpected exit {result.exit_code}",
    }


def _emit_failed(emit: _Emit | None, detail: str) -> None:
    if emit:
        emit(EventType.LOOT_FAILED, detail, drop_log=True)
