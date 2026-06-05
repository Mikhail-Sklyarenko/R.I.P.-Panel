"""Recovery после зависания: stop orchestrator + kill processes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from config.schema import AppConfig
from modules.utils.kill import KillResult, kill_all_with_confirm
from modules.utils.windows import MoveResult, move_all_cs_windows


@dataclass(frozen=True)
class RecoveryResult:
    kill: KillResult
    move: MoveResult | None = None

    @property
    def ok(self) -> bool:
        return self.kill.ok


def recover_hang(
    *,
    parent: Any | None = None,
    config: AppConfig | None = None,
    on_before_kill: Callable[[], None] | None = None,
) -> RecoveryResult:
    """
    Жёсткий recovery: остановить оркестратор (если callback задан), kill CS+Steam.
    """
    if on_before_kill:
        on_before_kill()
    kill = kill_all_with_confirm(parent=parent, config=config)
    return RecoveryResult(kill=kill)


def recover_move_windows(*, config: AppConfig | None = None) -> MoveResult:
    """Сдвинуть все CS окна (без kill)."""
    return move_all_cs_windows(config=config)
