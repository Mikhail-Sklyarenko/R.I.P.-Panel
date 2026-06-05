"""Get LVL: обновление level/xp в vault (SIM или Steam Web)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from modules.vault.store import AccountNotFoundError, load_account, update_account_meta


@dataclass(frozen=True)
class LevelSnapshot:
    login: str
    level: int
    xp: int
    source: str


def fetch_level(login: str) -> LevelSnapshot:
    """Прочитать уровень аккаунта; STEAM_LEVEL_SIM=1 для тестов/CI."""
    login = login.strip()
    try:
        meta = load_account(login)
    except AccountNotFoundError:
        raise

    if os.environ.get("STEAM_LEVEL_SIM") == "1":
        level = int(meta["level"]) + 1
        xp = int(meta.get("xp", 0)) + 100
        update_account_meta(login, level=level, xp=xp)
        return LevelSnapshot(login=login, level=level, xp=xp, source="sim")

    return _fetch_level_steam_web(login, current_level=int(meta["level"]))


def _fetch_level_steam_web(login: str, *, current_level: int) -> LevelSnapshot:
    """
    Публичный профиль Steam Community (без API key).
    На Windows при закрытом профиле может не сработать — тогда SIM/ручной ввод.
    """
    import urllib.error
    import urllib.request

    url = f"https://steamcommunity.com/id/{login}/?xml=1"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"steam profile fetch failed for {login}: {exc}") from exc

    level = current_level
    xp = 0
    m = re.search(r"<steamID64>(\d+)</steamID64>", body)
    if m:
        level_match = re.search(
            r"Level (\d+)",
            body,
        )
        if level_match:
            level = int(level_match.group(1))
    update_account_meta(login, level=level, xp=xp)
    return LevelSnapshot(login=login, level=level, xp=xp, source="steam_web")
