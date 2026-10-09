"""Regression checks for the single product entrypoint and stale settings."""

def test_product_mode_replaces_stale_environment(monkeypatch):
    from core.farm_runtime import configure_farm_runtime
    for key in ("CSGOBOT_NAV", "CSGOBOT_NAV_MODE", "CSGOBOT_NAV_PACK", "CSGOBOT_AUTO_ACTIVATE", "CSGOBOT_NAV_READ_ONLY"):
        monkeypatch.setenv(key, "old")
    monkeypatch.setenv("CSGOBOT_NAV_READ_ONLY", "1")
    configure_farm_runtime()
    import os
    assert os.environ["CSGOBOT_NAV"] == "1"
    assert os.environ["CSGOBOT_NAV_MODE"] == "expanded_roam"
    assert os.environ["CSGOBOT_NAV_PACK"] == "auto"
    assert os.environ["CSGOBOT_NAV_READ_ONLY"] == "1"


def test_expanded_worker_ignores_old_saved_pack(monkeypatch):
    from config.schema import AppConfig
    from modules.combat.csgobot_ai import _apply_child_env_from_ctx
    monkeypatch.setenv("CSGOBOT_NAV_MODE", "expanded_roam")
    child = {}
    _apply_child_env_from_ctx({"config": AppConfig(csgobot_nav_enabled=False, csgobot_nav_pack="dust2_dm")}, child)
    assert child["CSGOBOT_NAV"] == "1"
    assert child["CSGOBOT_NAV_MODE"] == "expanded_roam"
    assert child["CSGOBOT_NAV_PACK"] == "auto"


def test_worker_defaults_do_not_enable_macro(csgobot_path, monkeypatch):
    import run
    monkeypatch.delenv("CSGOBOT_NAV", raising=False)
    monkeypatch.delenv("CSGOBOT_LOOK", raising=False)
    config = run.create_config()
    assert config.nav.enabled
    assert not config.patrol.enabled
    assert not config.look.enabled
    assert not config.aim.auto_move
