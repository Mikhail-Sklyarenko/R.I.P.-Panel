"""FSM одной farm-сессии (1 acc = 1 CS2, solo Deathmatch)."""

from __future__ import annotations

from enum import Enum


class SessionState(str, Enum):
    """Состояние сессии в оркестраторе."""

    QUEUED = "queued"
    LAUNCHING = "launching"
    IN_MENU = "in_menu"
    SEARCHING_DM = "searching_dm"
    IN_DM = "in_dm"
    FARMING = "farming"
    LEVEL_UP = "level_up"
    DROP_PICKING = "drop_picking"
    LOOTING = "looting"
    CLEANUP = "cleanup"
    DONE = "done"
    FAILED = "failed"


class InvalidTransitionError(ValueError):
    """Запрещённый переход FSM."""

    def __init__(self, source: SessionState, target: SessionState) -> None:
        self.source = source
        self.target = target
        super().__init__(f"transition {source.value} -> {target.value} not allowed")


# Допустимые переходы: from -> {to, ...}
ALLOWED_TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
    SessionState.QUEUED: frozenset(
        {SessionState.LAUNCHING, SessionState.FAILED}
    ),
    SessionState.LAUNCHING: frozenset(
        {SessionState.IN_MENU, SessionState.CLEANUP, SessionState.FAILED}
    ),
    SessionState.IN_MENU: frozenset(
        {SessionState.SEARCHING_DM, SessionState.CLEANUP, SessionState.FAILED}
    ),
    SessionState.SEARCHING_DM: frozenset(
        {SessionState.IN_DM, SessionState.IN_MENU, SessionState.FAILED}
    ),
    SessionState.IN_DM: frozenset(
        {SessionState.FARMING, SessionState.CLEANUP, SessionState.FAILED}
    ),
    SessionState.FARMING: frozenset(
        {
            SessionState.LEVEL_UP,
            SessionState.FARMING,
            SessionState.CLEANUP,
            SessionState.FAILED,
        }
    ),
    SessionState.LEVEL_UP: frozenset(
        {SessionState.DROP_PICKING, SessionState.LOOTING, SessionState.FAILED}
    ),
    SessionState.DROP_PICKING: frozenset(
        {SessionState.LOOTING, SessionState.FAILED}
    ),
    SessionState.LOOTING: frozenset(
        {SessionState.CLEANUP, SessionState.FAILED}
    ),
    SessionState.CLEANUP: frozenset(
        {SessionState.DONE, SessionState.FAILED}
    ),
    SessionState.DONE: frozenset(),
    SessionState.FAILED: frozenset(),
}


def can_transition(source: SessionState, target: SessionState) -> bool:
    """Проверка перехода без побочных эффектов."""
    return target in ALLOWED_TRANSITIONS.get(source, frozenset())


def advance(source: SessionState, target: SessionState) -> SessionState:
    """Применить переход; ValueError если запрещён."""
    if not can_transition(source, target):
        raise InvalidTransitionError(source, target)
    return target
