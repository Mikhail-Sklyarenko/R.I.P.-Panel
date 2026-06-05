"""Режимы сессии оркестратора (B10)."""

from __future__ import annotations

from enum import Enum


class SessionMode(str, Enum):
    FULL = "full"
    LAUNCH_ONLY = "launch_only"
