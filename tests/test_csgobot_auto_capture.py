"""Unit tests for farm auto-capture (CT dataset collector)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.insert(0, str(_CSGOBOT))

from dataset_capture.config import resolve_auto_capture_config  # noqa: E402
from dataset_capture.controller import (  # noqa: E402
    AutoCaptureController,
    average_hash64,
    build_soft_labels,
    hamming64,
    has_soft_ct,
    xyxy_to_yolo_line,
)


def test_env_resolve_auto_capture(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_AUTO_CAPTURE", "1")
    monkeypatch.setenv("CSGOBOT_CAPTURE_INTERVAL_SEC", "1.5")
    monkeypatch.setenv("CSGOBOT_CAPTURE_MAX_PER_HOUR", "100")
    cfg = resolve_auto_capture_config(default_enabled=False)
    assert cfg.enabled is True
    assert cfg.interval_sec == 1.5
    assert cfg.max_per_hour == 100


def test_xyxy_to_yolo_line_normalized() -> None:
    line = xyxy_to_yolo_line(0, [320, 180, 480, 540], 1280, 720)
    assert line is not None
    parts = line.split()
    assert parts[0] == "0"
    assert 0.0 <= float(parts[1]) <= 1.0


def test_build_soft_labels_respects_class_conf() -> None:
    from dataset_capture.config import AutoCaptureConfig

    cfg = AutoCaptureConfig(
        label_conf_c=0.40,
        label_conf_ch=0.40,
        label_conf_t=0.50,
        min_bbox_height=10.0,
    )
    dets = {
        "c": [{"xyxy": [100, 100, 200, 300], "conf": 0.41}],
        "t": [{"xyxy": [300, 100, 400, 300], "conf": 0.45}],
    }
    lines = build_soft_labels(dets, width=1280, height=720, cfg=cfg)
    assert len(lines) == 1
    assert lines[0].startswith("0 ")


def test_has_soft_ct_band() -> None:
    dets = {"c": [{"xyxy": [1, 1, 2, 2], "conf": 0.42}]}
    assert has_soft_ct(dets, lo=0.30, hi=0.55) is True
    assert has_soft_ct(dets, lo=0.45, hi=0.55) is False


def test_ahash_similar_images() -> None:
    rng = np.random.default_rng(0)
    a = rng.integers(0, 255, size=(64, 64, 3), dtype=np.uint8)
    b = a.copy()
    b[0, 0] = (min(255, int(b[0, 0, 0]) + 1),) * 3
    ha = average_hash64(a)
    hb = average_hash64(b)
    assert hamming64(ha, hb) <= 4


def test_ahash_different_images() -> None:
    a = np.zeros((64, 64, 3), dtype=np.uint8)
    a[:, :32] = 255
    b = np.zeros((64, 64, 3), dtype=np.uint8)
    b[:32, :] = 255
    assert hamming64(average_hash64(a), average_hash64(b)) >= 8


def test_controller_timer_capture(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    from dataset_capture.config import AutoCaptureConfig

    cfg = AutoCaptureConfig(
        enabled=True,
        root_dir=str(tmp_path / "captures"),
        interval_sec=0.01,
        min_interval_sec=0.0,
        max_per_hour=50,
        max_mb=50,
        queue_size=8,
        dedup_hamming_max=0,
        pc_id="testpc",
        session_id="sess1",
        save_soft_labels=True,
        empty_scene_enabled=False,
    )
    ctl = AutoCaptureController(cfg, cwd=tmp_path, weights_name="w.pt")
    submitted: list = []

    def _fake_submit(job):
        submitted.append(job)
        return True

    ctl._writer.start = lambda: None  # type: ignore[method-assign]
    ctl._writer.submit = _fake_submit  # type: ignore[method-assign]
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    img[:] = (30, 40, 50)
    trigger = ctl.maybe_capture(
        img,
        detections={"c": [{"xyxy": [100, 100, 200, 280], "conf": 0.5, "cls": 0}]},
        team="t",
        activated=True,
        roi_used=False,
        enemy_classes=("c", "ch"),
        now=1000.0,
    )
    assert trigger in ("timer_t", "soft_ct", "enemy_appear", "timer")
    assert len(submitted) == 1
    assert f"__{trigger}" in submitted[0].stem
    assert submitted[0].label_lines
    ctl.stop()


def test_empty_scene_forces_empty_labels(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    from dataset_capture.config import AutoCaptureConfig

    cfg = AutoCaptureConfig(
        enabled=True,
        root_dir=str(tmp_path / "captures"),
        interval_sec=99.0,
        min_interval_sec=0.0,
        empty_scene_enabled=True,
        empty_scene_interval_sec=0.5,
        max_per_hour=50,
        max_mb=50,
        dedup_hamming_max=0,
        pc_id="pc",
        session_id="s1",
        save_soft_labels=True,
    )
    ctl = AutoCaptureController(cfg, cwd=tmp_path)
    submitted: list = []
    ctl._writer.start = lambda: None  # type: ignore[method-assign]
    ctl._writer.submit = lambda job: submitted.append(job) or True  # type: ignore[method-assign]
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    img[:] = (10, 20, 30)
    trigger = ctl.maybe_capture(
        img,
        detections={},
        team="ct",
        activated=True,
        roi_used=False,
        enemy_classes=("c", "ch", "t", "th"),
        now=2000.0,
    )
    assert trigger == "empty_scene"
    assert submitted[0].label_lines == []
    assert submitted[0].meta["force_empty"] is True
    ctl.stop()


def test_hard_neg_mode_texture_fp_empty_labels(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    from dataset_capture.config import AutoCaptureConfig

    cfg = AutoCaptureConfig(
        enabled=True,
        root_dir=str(tmp_path / "captures"),
        hard_neg_mode=True,
        hard_neg_interval_sec=0.5,
        min_interval_sec=0.0,
        max_per_hour=50,
        max_mb=50,
        dedup_hamming_max=0,
        pc_id="pc",
        session_id="hn1",
        save_soft_labels=True,
    )
    ctl = AutoCaptureController(cfg, cwd=tmp_path)
    submitted: list = []
    ctl._writer.start = lambda: None  # type: ignore[method-assign]
    ctl._writer.submit = lambda job: submitted.append(job) or True  # type: ignore[method-assign]
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    img[:] = (80, 70, 60)
    trigger = ctl.maybe_capture(
        img,
        detections={"c": [{"xyxy": [400, 200, 500, 400], "conf": 0.88, "cls": 0}]},
        team="t",
        activated=True,
        roi_used=False,
        enemy_classes=("c", "ch", "t", "th"),
        now=3000.0,
    )
    assert trigger == "texture_fp"
    assert submitted[0].label_lines == []
    assert submitted[0].meta["force_empty"] is True
    ctl.stop()


def test_env_hard_neg_resolve(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_AUTO_CAPTURE", "1")
    monkeypatch.setenv("CSGOBOT_CAPTURE_HARD_NEG", "1")
    monkeypatch.setenv("CSGOBOT_CAPTURE_EMPTY_SCENE", "0")
    cfg = resolve_auto_capture_config()
    assert cfg.enabled is True
    assert cfg.hard_neg_mode is True
    assert cfg.empty_scene_enabled is False
