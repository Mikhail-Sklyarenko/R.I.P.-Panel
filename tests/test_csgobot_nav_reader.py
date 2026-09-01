"""Tests for csgobot minimap nav (PR-N0/N1)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = _ROOT / "tests" / "fixtures" / "csgobot_nav"


@pytest.fixture(scope="module", autouse=True)
def _load_csgobot_nav(csgobot_module_path) -> None:
    g = globals()
    g["load_calibration"] = importlib.import_module("nav.calibration").load_calibration
    g["MinimapReader"] = importlib.import_module("nav.minimap_reader").MinimapReader
    g["load_nav_pack"] = importlib.import_module("nav.pack").load_nav_pack
    paths = importlib.import_module("nav.paths")
    g["resolve_calibration_path"] = paths.resolve_calibration_path
    g["resolve_map_meta_path"] = paths.resolve_map_meta_path
    g["resolve_map_radar_path"] = paths.resolve_map_radar_path
    g["resolve_nav_pack_path"] = paths.resolve_nav_pack_path
    g["PoseFilter"] = importlib.import_module("nav.pose_filter").PoseFilter


def test_nav_resources_exist() -> None:
    assert resolve_calibration_path().is_file()
    assert resolve_nav_pack_path("dust2_dm").is_file()
    assert resolve_map_meta_path("de_dust2").is_file()
    assert resolve_map_radar_path("de_dust2").is_file()


def test_load_calibration() -> None:
    cal = load_calibration(resolve_calibration_path())
    assert cal.resolution == (1280, 720)
    assert cal.minimap.rect.w > 100
    assert cal.minimap.player_icon.max_area_px >= cal.minimap.player_icon.min_area_px


def test_load_nav_pack() -> None:
    pack = load_nav_pack(resolve_nav_pack_path("dust2_dm"))
    assert pack.pack_id == "dust2_dm"
    assert pack.map_id == "de_dust2"
    assert pack.goal.id == "mid"
    assert 0.0 < pack.goal.x < 1.0
    assert pack.strategy == "route_cycle"
    assert len(pack.entries) >= 2


def test_map_meta_landmarks() -> None:
    meta = json.loads(resolve_map_meta_path("de_dust2").read_text(encoding="utf-8"))
    assert meta["map_id"] == "de_dust2"
    assert "mid" in meta["landmarks"]


def test_reader_on_fixtures() -> None:
    cal = load_calibration(resolve_calibration_path())
    reader = MinimapReader(cal)
    manifest = json.loads((_FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    labels = manifest["labels"]
    for name, spec in labels.items():
        path = _FIXTURES / name
        assert path.is_file(), name
        img = np.asarray(Image.open(path).convert("RGB"))
        pose = reader.read(img)
        if spec.get("expect_pose_valid", False):
            assert pose.valid, f"{name} pose invalid conf={pose.confidence}"
            assert 0.0 <= pose.x_norm <= 1.0
            assert 0.0 <= pose.y_norm <= 1.0
        if spec.get("expect_near_center"):
            assert abs(pose.x_norm - 0.5) < 0.15, name
            assert abs(pose.y_norm - 0.5) < 0.15, name


def test_pose_filter_holds_last_pose(csgobot_path) -> None:
    from nav.pose import PoseResult

    cal = load_calibration(resolve_calibration_path())
    filt = PoseFilter(cal.pose)
    good = PoseResult(0.4, 0.6, 10.0, 0.9, True, 20)
    out = filt.update(good, now=1.0)
    assert out.valid
    lost = PoseResult.invalid()
    out2 = filt.update(lost, now=1.2)
    assert out2.valid
    out3 = filt.update(lost, now=5.0)
    assert not out3.valid


def test_nav_config_resolve_env(monkeypatch, csgobot_path) -> None:
    from config import NavConfig
    from nav.config_resolve import resolve_nav_config

    monkeypatch.setenv("CSGOBOT_NAV", "1")
    monkeypatch.setenv("CSGOBOT_NAV_PACK", "dust2_dm")
    cfg = resolve_nav_config(NavConfig())
    assert cfg.enabled is True
    assert cfg.pack_id == "dust2_dm"
    assert cfg.read_only is False
