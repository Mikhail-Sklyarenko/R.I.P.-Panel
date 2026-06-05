"""Типы событий для JSONL (data/logs/events.jsonl) и UI-логов."""

from enum import Enum


class EventType(str, Enum):
    """Событие агента; значение = строка в JSONL."""

    # Сессия
    SESSION_START = "session_start"
    SESSION_DONE = "session_done"
    SESSION_FAILED = "session_failed"

    # Сеть / окружение (solo: без диспетчера)
    IP_OK = "ip_ok"

    # Launcher
    STEAM_LOGIN_START = "steam_login_start"
    STEAM_LOGIN_OK = "steam_login_ok"
    STEAM_LOGIN_FAILED = "steam_login_failed"
    STEAM_OK = "steam_ok"
    CS2_OK = "cs2_ok"

    # DM runner
    IN_MENU = "in_menu"
    SEARCHING_DM = "searching_dm"
    IN_DM = "in_dm"
    EXITED = "exited"

    # Combat / csgobot
    COMBAT_AI_STARTED = "combat_ai_started"
    COMBAT_STOPPED = "combat_stopped"
    COMBAT_FALLBACK = "combat_fallback"
    FARMING = "farming"
    COMBAT_TIMEOUT = "combat_timeout"

    # Прогресс фарма
    LEVEL_UP = "level_up"
    DROP_PICKED = "drop_picked"
    TELEGRAM_SENT = "telegram_sent"

    # Looter / vault
    LOOT_OK = "loot_ok"
    LOOT_FAILED = "loot_failed"

    # UI / оператор
    IDLE = "idle"
    OPERATOR_STOP = "operator_stop"
