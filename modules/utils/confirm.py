"""Опциональный confirm перед Kill (tkinter messagebox)."""

from __future__ import annotations

import os
from typing import Any

from config.loader import load_config
from config.schema import AppConfig


def should_confirm(config: AppConfig | None = None) -> bool:
    cfg = config or load_config()
    if os.environ.get("UTILS_SKIP_CONFIRM", "").lower() in ("1", "true", "yes"):
        return False
    return bool(cfg.utils_confirm_before_kill)


def confirm_kill(
    *,
    parent: Any | None = None,
    config: AppConfig | None = None,
    title: str = "Kill CS & Steam",
    message: str = (
        "Завершить все процессы CS2/CSGO и Steam?\n"
        "Используйте при зависании сессии (recovery)."
    ),
) -> bool:
    """True = пользователь подтвердил; False = отмена."""
    if not should_confirm(config):
        return True
    import tkinter as tk
    from tkinter import messagebox

    if parent is not None:
        try:
            return bool(
                messagebox.askyesno(title, message, parent=parent)
            )
        except tk.TclError:
            pass
    return bool(messagebox.askyesno(title, message))
