"""Stable reason codes; the panel shows the Russian text, logs keep the code."""
from __future__ import annotations

from enum import Enum


class Reason(str, Enum):
    OK = "ok"
    WAITING_AGENT = "waiting_agent"
    AGENT_SUSPECT = "agent_suspect"
    AGENT_OFFLINE = "agent_offline"
    PROTOCOL_MISMATCH = "protocol_mismatch"
    BUILD_MISMATCH = "build_mismatch"
    RESOURCE_MISMATCH = "resource_mismatch"
    IDENTITY_UNCONFIRMED = "identity_unconfirmed"
    ACCOUNT_MISMATCH = "account_mismatch"
    PREFLIGHT_FAILED = "preflight_failed"
    STEAM_NOT_RUNNING = "steam_not_running"
    CS2_NOT_RUNNING = "cs2_not_running"
    UNKNOWN_SCREEN = "unknown_screen"
    BLOCKING_MODAL = "blocking_modal"
    FRIEND_REQUEST_PENDING = "friend_request_pending"
    FRIENDSHIP_NOT_CONFIRMED = "friendship_not_confirmed"
    ACCOUNT_LIMITED = "account_limited"
    STEAM_GUARD_REQUIRED = "steam_guard_required"
    RATE_LIMITED = "rate_limited"
    LOBBY_WRONG_ROSTER = "lobby_wrong_roster"
    LOBBY_NOT_CONFIGURED = "lobby_not_configured"
    INVITE_NOT_RECEIVED = "invite_not_received"
    INVITE_NOT_ACCEPTED = "invite_not_accepted"
    LOBBY_RECREATE = "lobby_recreate"
    SEARCH_NOT_STARTED = "search_not_started"
    SEARCH_DESYNC = "search_desync"
    SEARCH_CANCELLED = "search_cancelled"
    CONFIRM_DESYNC = "confirm_desync"
    MATCH_LOAD_TIMEOUT = "match_load_timeout"
    MATCH_MISMATCH = "match_mismatch"
    MATCH_PROOF_UNAVAILABLE = "match_proof_unavailable"
    PLAYER_NOT_CONNECTED = "player_not_connected"
    GSI_STALE = "gsi_stale"
    CAPTURE_STALE = "capture_stale"
    COOLDOWN = "cooldown"
    CS2_UPDATE_REQUIRED = "cs2_update_required"
    MODE_UNAVAILABLE = "mode_unavailable"
    COMMAND_FAILED = "command_failed"
    COMMAND_TIMEOUT = "command_timeout"
    BUDGET_EXHAUSTED = "budget_exhausted"
    MISMATCH_LIMIT = "mismatch_limit"
    WORKER_FAILED = "worker_failed"
    OPERATOR_STOP = "operator_stop"
    OPERATOR_PAUSE = "operator_pause"
    CALIBRATION_MISSING = "calibration_missing"
    GAMEPLAY_NOT_ADMITTED = "gameplay_not_admitted"
    INPUT_BUSY = "input_busy"


# Reasons that must never be retried automatically.
MANUAL_ONLY = frozenset({
    Reason.ACCOUNT_MISMATCH,
    Reason.ACCOUNT_LIMITED,
    Reason.STEAM_GUARD_REQUIRED,
    Reason.PROTOCOL_MISMATCH,
    Reason.BUILD_MISMATCH,
    Reason.RESOURCE_MISMATCH,
    Reason.COOLDOWN,
    Reason.CS2_UPDATE_REQUIRED,
    Reason.CALIBRATION_MISSING,
    Reason.MATCH_PROOF_UNAVAILABLE,
})

TEXT_RU: dict[Reason, str] = {
    Reason.OK: "в порядке",
    Reason.WAITING_AGENT: "ожидание подключения агента",
    Reason.AGENT_SUSPECT: "связь с агентом нестабильна — новые действия запрещены",
    Reason.AGENT_OFFLINE: "агент недоступен — ввод отозван",
    Reason.PROTOCOL_MISMATCH: "несовместимая версия протокола агента",
    Reason.BUILD_MISMATCH: "версия программы отличается от координатора",
    Reason.RESOURCE_MISMATCH: "ресурсы (модели/профиль Inferno) отличаются",
    Reason.IDENTITY_UNCONFIRMED: "активный Steam-аккаунт не подтверждён",
    Reason.ACCOUNT_MISMATCH: "активен другой Steam-аккаунт — запуск запрещён",
    Reason.PREFLIGHT_FAILED: "не пройдена обязательная проверка готовности",
    Reason.STEAM_NOT_RUNNING: "Steam не запущен",
    Reason.CS2_NOT_RUNNING: "CS2 не запущена",
    Reason.UNKNOWN_SCREEN: "экран не распознан — действия запрещены",
    Reason.BLOCKING_MODAL: "открыто блокирующее окно",
    Reason.FRIEND_REQUEST_PENDING: "запрос в друзья отправлен, ожидается подтверждение",
    Reason.FRIENDSHIP_NOT_CONFIRMED: "дружба не подтверждена обеими сторонами",
    Reason.ACCOUNT_LIMITED: "аккаунт ограничен и не может добавлять друзей",
    Reason.STEAM_GUARD_REQUIRED: "Steam требует ручного подтверждения",
    Reason.RATE_LIMITED: "Steam временно ограничил действия",
    Reason.LOBBY_WRONG_ROSTER: "состав лобби не совпадает с ожидаемым",
    Reason.LOBBY_NOT_CONFIGURED: "режим «Напарники» / Inferno не подтверждён",
    Reason.INVITE_NOT_RECEIVED: "приглашение не получено ведомым",
    Reason.INVITE_NOT_ACCEPTED: "приглашение получено, принятие не подтверждено",
    Reason.LOBBY_RECREATE: "лобби пересоздаётся",
    Reason.SEARCH_NOT_STARTED: "поиск не подтверждён",
    Reason.SEARCH_DESYNC: "поиск идёт не у всех участников",
    Reason.SEARCH_CANCELLED: "поиск отменён",
    Reason.CONFIRM_DESYNC: "подтверждение матча появилось не у обеих пар — разные матчи",
    Reason.MATCH_LOAD_TIMEOUT: "загрузка матча зависла",
    Reason.MATCH_MISMATCH: "пары попали в разные матчи — выход и повторный поиск",
    Reason.MATCH_PROOF_UNAVAILABLE: "общий матч невозможно доказать — нужна проверка оператора",
    Reason.PLAYER_NOT_CONNECTED: "участник не подключился к матчу",
    Reason.GSI_STALE: "данные GSI устарели",
    Reason.CAPTURE_STALE: "захват изображения не обновляется",
    Reason.COOLDOWN: "обнаружен cooldown поиска",
    Reason.CS2_UPDATE_REQUIRED: "CS2 требует обновления",
    Reason.MODE_UNAVAILABLE: "режим или карта временно недоступны",
    Reason.COMMAND_FAILED: "команда не выполнена",
    Reason.COMMAND_TIMEOUT: "результат команды не подтверждён вовремя",
    Reason.BUDGET_EXHAUSTED: "исчерпан лимит попыток восстановления",
    Reason.MISMATCH_LIMIT: "превышен лимит повторных поисков",
    Reason.WORKER_FAILED: "игровой процесс завершился с ошибкой",
    Reason.OPERATOR_STOP: "остановлено оператором",
    Reason.OPERATOR_PAUSE: "приостановлено оператором",
    Reason.CALIBRATION_MISSING: "нет калибровки меню CS2 для этого ПК",
    Reason.GAMEPLAY_NOT_ADMITTED: "игровой допуск не выдан координатором",
    Reason.INPUT_BUSY: "ввод занят другим владельцем",
}


def describe(reason: Reason | str, detail: str = "") -> str:
    try:
        text = TEXT_RU[Reason(reason)]
    except ValueError:
        text = str(reason)
    return f"{text}: {detail}" if detail else text
