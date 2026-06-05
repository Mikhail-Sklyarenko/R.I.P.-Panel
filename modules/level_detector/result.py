"""Результат наблюдения во время combat."""

from __future__ import annotations

from enum import Enum


class WatchResult(str, Enum):
    LEVEL_UP = "level_up"
    COMBAT_TIMEOUT = "combat_timeout"
    STOPPED = "stopped"
