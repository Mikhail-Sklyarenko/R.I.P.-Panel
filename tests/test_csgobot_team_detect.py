"""csgobot HUD team auto-detect (PR-T1)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.insert(0, str(_CSGOBOT))

from config import TeamDetectConfig  # noqa: E402
from aim_tuning import resolve_auto_team_enabled  # noqa: E402
from team.hud_team_detect import (  # noqa: E402
    TeamDetectState,
    detect_team_hud,
    score_probes,
    update_team_hysteresis,
)
from team.paths import resolve_team_probes_path  # noqa: E402
from team.probes import load_team_probes  # noqa: E402

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "csgobot_team"


def _load_fixture(name: str) -> np.ndarray:
    path = _FIXTURES / name
    raw = Image.open(path).convert("RGB")
    if raw.size != (1280, 720):
        raw = raw.resize((1280, 720), Image.Resampling.LANCZOS)
    return np.asarray(raw)


def _probe_set():
    return load_team_probes(resolve_team_probes_path())


def test_ct_fixture_classifies_ct() -> None:
    probes = _probe_set()
    for name in ("t1_ct_dm_01.png", "t1_ct_dm_02.png", "t1_ct_dm_03.png"):
        img = _load_fixture(name)
        assert detect_team_hud(img, probes) == "ct"


def test_t_fixture_classifies_t() -> None:
    probes = _probe_set()
    img = _load_fixture("t1_t_dm_01.png")
    assert detect_team_hud(img, probes) == "t"


def test_ct_probes_do_not_match_t_image() -> None:
    probes = _probe_set()
    img = _load_fixture("t1_t_dm_01.png")
    assert score_probes(img, probes.ct) == 0


def test_t_probes_do_not_match_ct_image() -> None:
    probes = _probe_set()
    img = _load_fixture("t1_ct_dm_01.png")
    assert score_probes(img, probes.t) == 0


def test_team_select_is_ambiguous() -> None:
    probes = _probe_set()
    img = _load_fixture("t1_team_select.png")
    assert detect_team_hud(img, probes) is None


def test_hysteresis_requires_confirm_frames() -> None:
    state = TeamDetectState.from_team("ct")
    changed, pending = update_team_hysteresis(
        state, "t", confirm_frames=3,
    )
    assert changed is None
    assert pending == 1

    changed, pending = update_team_hysteresis(state, "t", confirm_frames=3)
    assert changed is None
    assert pending == 2

    changed, pending = update_team_hysteresis(state, "t", confirm_frames=3)
    assert changed == "t"
    assert state.confirmed_team == "t"


def test_hysteresis_resets_on_ambiguous() -> None:
    state = TeamDetectState.from_team("ct")
    update_team_hysteresis(state, "t", confirm_frames=3)
    changed, pending = update_team_hysteresis(state, None, confirm_frames=3)
    assert changed is None
    assert pending == 0
    assert state.pending_team is None


def test_create_config_team_detect_defaults() -> None:
    from run import create_config

    cfg = create_config()
    assert cfg.team_detect.enabled is True
    assert cfg.team_detect.confirm_frames == 3
    assert cfg.team_detect.manual_override_sec == 5.0


def test_env_CSGOBOT_AUTO_TEAM_disables() -> None:
    os.environ["CSGOBOT_AUTO_TEAM"] = "0"
    try:
        assert resolve_auto_team_enabled(True) is False
    finally:
        os.environ.pop("CSGOBOT_AUTO_TEAM", None)
