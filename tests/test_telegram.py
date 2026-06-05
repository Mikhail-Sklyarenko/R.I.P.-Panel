"""B11: Telegram SIM, drop notify, test ping."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config.loader import ensure_config, load_config, save_config
from config.paths import get_artifacts_dir, get_data_dir
from config.schema import AppConfig
from core.events import EventType
from modules.drop_picker import pick_care_package
from modules.telegram import format_drop_caption, send_test_ping
from modules.telegram.client import send_message, send_photo
from modules.telegram.notify import find_drop_screenshot, notify_drop
from modules.drop_picker.pricing import price_slots

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "drop_picker"
NAMES = [
    "AK-47 | Redline (Field-Tested)",
    "Glock-18 | Water Elemental (Minimal Wear)",
    "MP9 | Storm (Factory New)",
    "P250 | Sand Dune (Battle-Scarred)",
]


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_SIM", "1")
    monkeypatch.setenv("DROP_PICKER_SIM", "1")
    monkeypatch.setenv("DROP_PRICING_OFFLINE", "1")
    ensure_config()
    return tmp_path


def test_send_message_sim_writes_outbox(data_dir) -> None:
    cfg = load_config()
    cfg.telegram_bot_token = "123456:TESTTOKEN"
    cfg.telegram_chat_id = "-1001"
    save_config(cfg)
    result = send_message(cfg.telegram_bot_token, cfg.telegram_chat_id, "hello")
    assert result.ok
    assert result.simulated
    outbox = get_data_dir() / "telegram_sim" / "outbox.jsonl"
    assert outbox.is_file()
    line = json.loads(outbox.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert line["method"] == "sendMessage"
    assert "TESTTOKEN" not in line.get("text", "") or line["text"] == "hello"


def test_send_test_ping_with_screenshot_sim(data_dir) -> None:
    cfg = load_config()
    cfg.telegram_bot_token = "tok"
    cfg.telegram_chat_id = "1"
    cfg.telegram_send_screenshot = True
    save_config(cfg)
    result = send_test_ping(cfg)
    assert result.ok
    assert result.method == "sendPhoto"


def test_notify_drop_uses_artifact_screenshot(data_dir) -> None:
    cfg = load_config()
    cfg.telegram_bot_token = "tok"
    cfg.telegram_chat_id = "1"
    save_config(cfg)
    events: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", *, drop_log: bool = False) -> None:
        events.append((event, detail))

    ctx = {
        "login": "acc1",
        "session_id": "sess01",
        "config": cfg,
        "emit": emit,
    }
    pick_care_package(ctx)
    shot = find_drop_screenshot("sess01")
    assert shot is not None
    priced = price_slots([(i + 1, n) for i, n in enumerate(NAMES)])
    result = notify_drop(ctx, picks=priced[:2])
    assert result is not None
    assert result.method == "sendPhoto"
    assert any(e[0] is EventType.TELEGRAM_SENT for e in events)


def test_format_drop_caption() -> None:
    priced = price_slots([(1, NAMES[0]), (2, NAMES[1])])
    text = format_drop_caption("user1", priced[:2])
    assert "user1" in text
    assert "AK-47" in text


def test_notify_skips_without_credentials(data_dir) -> None:
    cfg = AppConfig()
    assert notify_drop({"login": "x", "config": cfg}, picks=[]) is None


def test_test_ping_requires_config(data_dir) -> None:
    from modules.telegram import TelegramError

    with pytest.raises(TelegramError, match="telegram_bot_token"):
        send_test_ping(AppConfig())
