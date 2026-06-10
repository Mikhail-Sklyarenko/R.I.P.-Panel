"""Unit tests for csgobot patrol (relative WASD macro)."""

from __future__ import annotations

import sys
from pathlib import Path

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.insert(0, str(_CSGOBOT))

from patrol.loader import parse_patrol_data  # noqa: E402
from patrol.runner import PatrolRunner  # noqa: E402
from patrol.schema import PatrolScript, PatrolStep  # noqa: E402
from patrol.state import (  # noqa: E402
    PatrolMode,
    next_mode_after_combat_check,
    should_patrol_tick,
)


def _script() -> PatrolScript:
    return PatrolScript(
        name="test",
        loop=True,
        steps=[
            PatrolStep(key="w", sec=2.0),
            PatrolStep(key="d", sec=1.0),
        ],
    )


def test_parse_patrol_data() -> None:
    script = parse_patrol_data(
        {
            "name": "generic_dm",
            "loop": True,
            "steps": [{"key": "w", "sec": 4}],
        }
    )
    assert script.name == "generic_dm"
    assert len(script.steps) == 1
    assert script.steps[0].key == "w"


def test_runner_holds_key_for_step_duration() -> None:
    down: list[str] = []
    up: list[str] = []

    runner = PatrolRunner(
        _script(),
        key_down=down.append,
        key_up=up.append,
    )
    runner.tick(0.0)
    assert down == ["w"]
    assert up == []

    runner.tick(1.0)
    assert down == ["w"]
    runner.tick(2.0)
    assert up == ["w"]
    assert down == ["w", "d"]

    runner.pause()
    assert up == ["w", "d"]


def test_runner_loops() -> None:
    down: list[str] = []
    runner = PatrolRunner(_script(), key_down=down.append, key_up=lambda k: None)
    runner.tick(0.0)
    assert down == ["w"]
    runner.tick(2.0)
    assert down == ["w", "d"]
    runner.tick(3.0)
    assert down[-1] == "w"
    assert runner.step_index == 0


def test_combat_mode_transitions() -> None:
    mode = next_mode_after_combat_check(
        mode=PatrolMode.PATROL,
        in_combat=True,
        now=10.0,
        last_enemy_seen=10.0,
        combat_clear_sec=0.75,
    )
    assert mode == PatrolMode.COMBAT

    mode = next_mode_after_combat_check(
        mode=PatrolMode.COMBAT,
        in_combat=False,
        now=10.76,
        last_enemy_seen=10.0,
        combat_clear_sec=0.75,
    )
    assert mode == PatrolMode.PATROL

    mode = next_mode_after_combat_check(
        mode=PatrolMode.COMBAT,
        in_combat=False,
        now=10.5,
        last_enemy_seen=10.0,
        combat_clear_sec=0.75,
    )
    assert mode == PatrolMode.COMBAT


def test_should_patrol_tick() -> None:
    assert should_patrol_tick(
        patrol_enabled=True,
        activated=True,
        mode=PatrolMode.PATROL,
    )
    assert not should_patrol_tick(
        patrol_enabled=True,
        activated=True,
        mode=PatrolMode.COMBAT,
    )


def test_load_generic_dm_yaml() -> None:
    from patrol.loader import load_patrol  # noqa: E402
    from patrol.paths import resolve_patrol_path  # noqa: E402

    path = resolve_patrol_path("generic_dm")
    script = load_patrol(path)
    assert script.name == "generic_dm"
    assert len(script.steps) >= 3
