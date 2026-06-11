"""Startup warnings: trade_offer_link, YOLO weights, OBS VC."""

from __future__ import annotations

from unittest.mock import patch

from config.schema import AppConfig
from core.startup_checks import collect_startup_warnings


@patch("shutil.which", return_value="/usr/bin/node")
def test_warn_empty_trade_offer_link_when_auto_collect(_which, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    cfg = AppConfig(
        auto_collect_drop=True,
        trade_offer_link="",
    )
    warnings = collect_startup_warnings(cfg)
    assert any("trade_offer_link empty" in w for w in warnings)


@patch("shutil.which", return_value="/usr/bin/node")
def test_no_trade_link_warn_when_auto_collect_off(_which, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    cfg = AppConfig(
        auto_collect_drop=False,
        trade_offer_link="",
    )
    warnings = collect_startup_warnings(cfg)
    assert not any("trade_offer_link empty" in w for w in warnings)


@patch("shutil.which", return_value="/usr/bin/node")
@patch("modules.combat.csgobot_ai.check_cuda_torch", return_value=(True, {"cuda": True, "device": "GPU"}))
@patch("modules.combat.csgobot_ai.check_csgobot_preflight", return_value=(True, []))
@patch("modules.combat.csgobot_ai.check_obs_virtual_camera", return_value=(False, "not found"))
@patch("modules.combat.csgobot_ai.is_installed", return_value=True)
@patch("modules.combat.csgobot_ai.python_executable", return_value=__import__("pathlib").Path("python.exe"))
def test_warn_obs_vc_missing(
    _py: object,
    _installed: object,
    _obs: object,
    _preflight: object,
    _which: object,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("sys.platform", "win32")
    cfg = AppConfig(
        steam_path=r"C:\Steam\steam.exe",
        cs2_path=r"C:\CS2\cs2.exe",
        bot_mode="ai",
    )
    warnings = collect_startup_warnings(cfg)
    assert any("OBS Virtual Camera not found" in w for w in warnings)


@patch("shutil.which", return_value="/usr/bin/node")
@patch("modules.combat.csgobot_ai.check_cuda_torch", return_value=(True, {"cuda": True, "device": "GPU"}))
@patch(
    "modules.combat.csgobot_ai.check_csgobot_preflight",
    return_value=(False, ["weights missing: cs2_yolov8m_640_augmented_v4.pt"]),
)
@patch("modules.combat.csgobot_ai.check_obs_virtual_camera", return_value=(True, ""))
@patch("modules.combat.csgobot_ai.is_installed", return_value=True)
@patch("modules.combat.csgobot_ai.python_executable", return_value=__import__("pathlib").Path("python.exe"))
def test_warn_yolo_weights_missing(
    _py: object,
    _installed: object,
    _obs: object,
    _preflight: object,
    _which: object,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("sys.platform", "win32")
    cfg = AppConfig(
        steam_path=r"C:\Steam\steam.exe",
        cs2_path=r"C:\CS2\cs2.exe",
        bot_mode="ai",
    )
    warnings = collect_startup_warnings(cfg)
    assert any("weights missing" in w for w in warnings)
