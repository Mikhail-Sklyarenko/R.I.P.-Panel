"""Модели строк UI (без секретов vault)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AccountRow:
    login: str
    level: int = 0
    xp: int = 0
    farmed_this_week: bool = False
    selected: bool = False
    status: str = "idle"

    @property
    def status_color(self) -> str:
        if self.farmed_this_week:
            return "#6b7280"
        if self.status == "farming":
            return "#f59e0b"
        if self.status == "error":
            return "#ef4444"
        if self.status == "done":
            return "#22c55e"
        return "#3b82f6"
