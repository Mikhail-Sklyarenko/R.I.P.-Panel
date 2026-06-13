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


def test_fsm_has_team_rifle_aliases() -> None:
    text = _fsm_cfg()
    assert 'alias buy_rifle_ct "buy m4a1; buy vesthelm"' in text
    assert 'alias buy_rifle_t "buy ak47; buy vesthelm"' in text


def test_fsm_binds_f9_f10() -> None:
    text = _fsm_cfg()
    assert 'bind f9 "buy_rifle_ct"' in text
    assert 'bind f10 "buy_rifle_t"' in text


def test_fsm_buy_commands_present() -> None:
    text = _fsm_cfg()
    assert "buy ak47" in text
    assert "buy m4a1" in text


def test_convars_disable_random_dm_weapons() -> None:
    text = _convars()
    assert '"cl_dm_buyrandomweapons"' in text
    assert '"false"' in text.split("cl_dm_buyrandomweapons")[1][:30]


def test_autobuy_binds_do_not_conflict_with_molotov() -> None:
    text = _fsm_cfg()
    assert "scancode12" in text
    assert "scancode39" in text
    assert "bind f9" in text
    assert "bind f10" in text
