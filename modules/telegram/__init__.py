"""Telegram: дроп + скриншот (Config #2), без токенов в git."""

from __future__ import annotations

from typing import Any

from modules.telegram.errors import TelegramError
from modules.telegram.notify import format_drop_caption, notify_drop, send_test_ping


def notify(ctx: dict[str, Any] | None = None) -> None:
    """Legacy alias: notify_drop из ctx (picks + session_id)."""
    if ctx is None:
        return
    picks = ctx.get("picks") or []
    notify_drop(ctx, picks=picks)


__all__ = [
    "TelegramError",
    "format_drop_caption",
    "notify",
    "notify_drop",
    "send_test_ping",
]
