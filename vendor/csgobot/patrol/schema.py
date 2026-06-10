"""Patrol script data model (relative WASD macro, not map coordinates)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

VALID_KEYS = frozenset({"w", "a", "s", "d"})


@dataclass(frozen=True)
class PatrolStep:
    key: str
    sec: float


@dataclass(frozen=True)
class PatrolScript:
    name: str
    loop: bool
    steps: List[PatrolStep]
