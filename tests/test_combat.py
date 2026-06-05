"""B6: combat factory, simple 10min, ai/fallback."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from config.loader import ensure_config, load_config, save_config
from config.schema import AppConfig, BotMode
from core.events import EventType
from modules.combat import csgobot_ai, factory, simple
from modules.combat.factory import resolve_mode, run_combat


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    ensure_config()
    return tmp_path


def test_resolve_mode_auto_without_csgobot(data_dir) -> None:
    cfg = load_config().model_copy(update={"bot_mode": BotMode.AUTO})
    assert resolve_mode(cfg) == BotMode.SIMPLE


def test_resolve_mode_auto_with_csgobot(data_dir, monkeypatch) -> None:
    monkeypatch.setattr(csgobot_ai, "is_installed", lambda: True)
    monkeypatch.setattr(
        csgobot_ai,
        "python_executable",
        lambda: __import__("pathlib").Path("C:/fake/python.exe"),
    )
    cfg = AppConfig(bot_mode=BotMode.AUTO)
    assert resolve_mode(cfg) == BotMode.AI


def test_simple_runs_ten_minutes_equivalent(data_dir, monkeypatch) -> None:
    monkeypatch.setenv("COMBAT_SIMPLE_SECONDS", "2")
    events: list[EventType] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        events.append(event)

    t0 = __import__("time").monotonic()
    simple.run_simple({"emit": emit, "COMBAT_SKIP_WIN32": "1"}, minutes=10)
    elapsed = __import__("time").monotonic() - t0
    assert elapsed >= 1.8
    assert EventType.FARMING in events
    assert EventType.COMBAT_STOPPED in events


def test_auto_emits_fallback_when_ai_missing(data_dir, monkeypatch) -> None:
    monkeypatch.setenv("COMBAT_SIMPLE_SECONDS", "1")
    events: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        events.append((event, detail))

    cfg = AppConfig(bot_mode=BotMode.AUTO, combat_simple_minutes=10)
    ok = run_combat({"emit": emit, "config": cfg})
    assert ok is True
    types = [e for e, _ in events]
    assert resolve_mode(cfg) == BotMode.SIMPLE
    assert EventType.FARMING in types


@patch("modules.combat.csgobot_ai.start_ai", return_value=False)
def test_ai_mode_fallback_then_simple(
    mock_ai: MagicMock, data_dir, monkeypatch
) -> None:
    monkeypatch.setenv("COMBAT_SIMPLE_SECONDS", "1")
    events: list[EventType] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        events.append(event)

    cfg = AppConfig(bot_mode=BotMode.AI)
    ok = run_combat({"emit": emit, "config": cfg})
    assert ok is True
    mock_ai.assert_called_once()
    assert EventType.COMBAT_FALLBACK in events
    assert EventType.FARMING in events


@patch("modules.combat.csgobot_ai.start_ai", return_value=True)
def test_ai_success_no_fallback(mock_ai: MagicMock, data_dir) -> None:
    events: list[EventType] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        events.append(event)

    cfg = AppConfig(bot_mode=BotMode.AI)
    assert run_combat({"emit": emit, "config": cfg}) is True
    assert EventType.COMBAT_FALLBACK not in events


def test_no_gpl_import_in_panel() -> None:
    import panel.app
    import panel.controller
    import panel.ui

    for mod in (panel.app, panel.controller, panel.ui):
        src = open(mod.__file__, encoding="utf-8").read()
        assert "csgobot" not in src
        assert "vendor.csgobot" not in src
