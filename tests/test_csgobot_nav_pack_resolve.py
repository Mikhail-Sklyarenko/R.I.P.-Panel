"""Tests for nav pack resolution (PR-N6)."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module", autouse=True)
def _load_pack_resolve(csgobot_module_path) -> None:
    from nav import pack_resolve

    globals()["pack_resolve"] = pack_resolve


def test_nav_pack_for_script_auto() -> None:
    assert pack_resolve.nav_pack_for_script("dust2", "auto") == "dust2_dm"
    assert pack_resolve.nav_pack_for_script("mirage", "auto") == "mirage_dm"
    assert pack_resolve.nav_pack_for_script("generic_dm", "auto") == "generic_dm"
    assert pack_resolve.nav_pack_for_script("unknown", "auto") is None


def test_nav_pack_for_script_explicit() -> None:
    assert pack_resolve.nav_pack_for_script("mirage", "dust2_dm") == "dust2_dm"


def test_resolve_initial_nav_pack_id() -> None:
    assert (
        pack_resolve.resolve_initial_nav_pack_id(
            explicit_pack="auto",
            patrol_script="mirage",
        )
        == "mirage_dm"
    )
    assert (
        pack_resolve.resolve_initial_nav_pack_id(
            explicit_pack="auto",
            patrol_script="generic_dm",
        )
        == "generic_dm"
    )


def test_iter_preflight_pack_ids_auto() -> None:
    packs = pack_resolve.iter_preflight_pack_ids("auto")
    assert "dust2_dm" in packs
    assert "mirage_dm" in packs
    assert "generic_dm" in packs


def test_nav_preflight_mirage_pack(csgobot_path) -> None:
    from nav.preflight import run_nav_preflight

    result = run_nav_preflight(pack_id="mirage_dm")
    assert result["ok"] is True
    assert result["pack_id"] == "mirage_dm"
    assert result["map_id"] == "de_mirage"
    assert "mid" in result["goals"]


def test_nav_preflight_auto_checks_all(csgobot_path) -> None:
    from nav.preflight import run_nav_preflight

    result = run_nav_preflight(pack_id="auto")
    assert result["ok"] is True
    assert result["pack_id"] == "auto"
    assert "dust2_dm" in result["packs_ok"]
    assert "mirage_dm" in result["packs_ok"]
    assert "generic_dm" in result["packs_ok"]
