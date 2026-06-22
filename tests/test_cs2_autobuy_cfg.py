"""CS2 DM autobuy cfg: rifle aliases, binds, convars."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _fsm_cfg() -> str:
    return (_ROOT / "resources" / "cs2" / "fsm.cfg").read_text(encoding="utf-8")


def _convars() -> str:
    return (_ROOT / "resources" / "cs2" / "cs2_machine_convars.vcfg").read_text(
        encoding="utf-8"
    )


def test_fsm_has_team_agnostic_rifle_alias() -> None:
    text = _fsm_cfg()
    assert "alias buy_rifle_dm" in text
    assert "buy ak47" in text
    assert "buy m4a1_silencer" in text
    assert "buy vesthelm" in text


def test_fsm_binds_autobuy_keys() -> None:
    text = _fsm_cfg()
    assert 'bind f5 "buy_rifle_dm"' in text
    assert 'bind scancode63 "buy_rifle_dm"' in text
    assert 'bind insert "buy_rifle_dm"' in text
    assert 'bind o "buy_rifle_dm"' in text
    assert 'bind p "buy_rifle_dm"' in text


def test_fsm_buy_commands_present() -> None:
    text = _fsm_cfg()
    assert "buy ak47" in text
    assert "buy m4a1_silencer" in text
    assert "buy m4a4" in text


def test_fsm_sets_cl_dm_buyrandomweapons_off() -> None:
    text = _fsm_cfg()
    assert "cl_dm_buyrandomweapons 0" in text


def test_convars_disable_random_dm_weapons() -> None:
    text = _convars()
    assert '"cl_dm_buyrandomweapons"' in text
    assert '"false"' in text.split("cl_dm_buyrandomweapons")[1][:30]
