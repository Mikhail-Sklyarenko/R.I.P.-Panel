"""Live Windows test: CS2 care package + OCR (optional)."""

from __future__ import annotations

import os
import sys

import pytest

from config.loader import load_config
from modules.drop_picker import pick_care_package


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
@pytest.mark.live
def test_live_drop_picker_top2() -> None:
    """
    Запуск: RUN_DROP_LIVE=1 pytest tests/test_drop_picker_live.py -v
    Требует: CS2 на экране Care Package, 360x270, опционально pytesseract.
    """
    if os.environ.get("RUN_DROP_LIVE") != "1":
        pytest.skip("set RUN_DROP_LIVE=1 to run live drop picker test")

    events: list[str] = []

    def emit(event, detail: str = "", **kwargs) -> None:
        events.append(f"{event.value}: {detail}")

    result = pick_care_package(
        {
            "emit": emit,
            "config": load_config(),
            "session_id": "live_drop",
        }
    )
    assert result["ok"] is True
    assert len(result.get("picked", [])) == 2
    assert any("drop_picked" in e for e in events)
