"""Уведомления: дроп + скриншот из B8 artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from config.loader import load_config
from config.paths import get_artifacts_dir, get_data_dir
from config.schema import AppConfig
from modules.telegram.client import SendResult, send_message, send_photo
from modules.telegram.errors import TelegramError
from modules.ui_nav.artifacts import ArtifactStore


def _credentials(config: AppConfig) -> tuple[str, str]:
    return (config.telegram_bot_token.strip(), config.telegram_chat_id.strip())


def find_drop_screenshot(session_id: str) -> Path | None:
    """Главный кадр CARE_PACKAGE из data/artifacts/{session_id}/."""
    root = get_artifacts_dir(session_id)
    if not root.is_dir():
        return None
    patterns = (
        "*drop_input*.png",
        "*care_package*.png",
        "*drop_care_package*.png",
        "*.png",
    )
    for pattern in patterns:
        matches = sorted(root.glob(pattern))
        if matches:
            return matches[0]
    return None


def format_drop_caption(
    login: str,
    picks: Sequence[Any],
) -> str:
    lines = [f"Drop — {login}", "Top 2:"]
    for p in picks:
        name = getattr(p, "market_hash_name", None) or getattr(p, "name", "?")
        price = float(getattr(p, "price_usd", 0.0))
        slot_id = getattr(p, "slot_id", "?")
        lines.append(f"  #{slot_id} {name} — ${price:.2f}")
    return "\n".join(lines)


def notify_drop(
    ctx: dict[str, Any],
    *,
    picks: Sequence[Any],
    artifacts: ArtifactStore | None = None,
) -> SendResult | None:
    """
    После drop_picker: текст + скрин (если telegram_send_screenshot).
    Не бросает наружу — только возвращает None при пропуске.
    """
    config: AppConfig | None = ctx.get("config")
    if config is None:
        config = load_config()
    token, chat_id = _credentials(config)
    if not token or not chat_id:
        return None

    login = str(ctx.get("login", "unknown"))
    session_id = str(ctx.get("session_id", "drop"))
    caption = format_drop_caption(login, picks)

    try:
        if config.telegram_send_screenshot:
            shot = find_drop_screenshot(session_id)
            if shot is not None:
                return send_photo(token, chat_id, shot, caption)
        return send_message(token, chat_id, caption)
    except TelegramError:
        return None


def send_test_ping(config: AppConfig | None = None) -> SendResult:
    """Кнопка Test Telegram в UI."""
    cfg = config or load_config()
    token, chat_id = _credentials(cfg)
    if not token or not chat_id:
        raise TelegramError("Set telegram_bot_token and telegram_chat_id in Config #2")

    text = "Farm Panel: Telegram test OK"
    if cfg.telegram_send_screenshot:
        shot = _ensure_test_image()
        return send_photo(token, chat_id, shot, text)
    return send_message(token, chat_id, text)


def _ensure_test_image() -> Path:
    from PIL import Image

    root = get_data_dir() / "telegram_sim"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "test_ping.png"
    if not path.is_file():
        Image.new("RGB", (64, 64), (40, 120, 200)).save(path)
    return path
