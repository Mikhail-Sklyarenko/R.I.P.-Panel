"""Детекция level up / combat timeout во время фарма в DM."""

from __future__ import annotations

from modules.level_detector.result import WatchResult
from modules.level_detector.watch import watch

__all__ = ["WatchResult", "watch"]
