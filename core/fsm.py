"""Связь событий EventType с целевыми состояниями FSM (для оркестратора)."""

from __future__ import annotations

from core.events import EventType
from core.session_state import SessionState, advance

# Событие подразумевает переход в target, если текущее состояние допускает его.
EVENT_TARGET_STATE: dict[EventType, SessionState] = {
    EventType.SESSION_START: SessionState.LAUNCHING,
    EventType.STEAM_OK: SessionState.LAUNCHING,
    EventType.CS2_OK: SessionState.IN_MENU,
    EventType.IN_MENU: SessionState.IN_MENU,
    EventType.SEARCHING_DM: SessionState.SEARCHING_DM,
    EventType.IN_DM: SessionState.IN_DM,
    EventType.FARMING: SessionState.FARMING,
    EventType.LEVEL_UP: SessionState.LEVEL_UP,
    EventType.DROP_PICKED: SessionState.DROP_PICKING,
    EventType.LOOT_OK: SessionState.LOOTING,
    EventType.EXITED: SessionState.CLEANUP,
    EventType.SESSION_DONE: SessionState.DONE,
    EventType.SESSION_FAILED: SessionState.FAILED,
    EventType.LOOT_FAILED: SessionState.FAILED,
    EventType.OPERATOR_STOP: SessionState.FAILED,
    EventType.COMBAT_TIMEOUT: SessionState.CLEANUP,
}


def apply_event(current: SessionState, event: EventType) -> SessionState:
    """Перейти по событию; COMBAT_FALLBACK и др. не меняют state (остаётся FARMING)."""
    target = EVENT_TARGET_STATE.get(event)
    if target is None:
        return current
    if target == current:
        return current
    return advance(current, target)
