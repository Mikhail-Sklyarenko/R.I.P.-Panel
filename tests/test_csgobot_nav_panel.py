"""Panel integration for minimap nav (PR-N5)."""

from __future__ import annotations

from unittest.mock import patch


def test_apply_child_env_sets_nav_from_panel_config() -> None:
    from config.schema import AppConfig, BotMode
    from modules.combat import csgobot_ai

    child_env: dict[str, str] = {}
    cfg = AppConfig(
        bot_mode=BotMode.AI,
        csgobot_nav_enabled=True,
        csgobot_nav_pack="auto",
    )
    csgobot_ai._apply_child_env_from_ctx({"config": cfg}, child_env)
    assert child_env["CSGOBOT_NAV"] == "1"
    assert child_env["CSGOBOT_NAV_PACK"] == "auto"


def test_apply_child_env_nav_disabled() -> None:
    from config.schema import AppConfig, BotMode
    from modules.combat import csgobot_ai

    child_env: dict[str, str] = {}
    cfg = AppConfig(bot_mode=BotMode.AI, csgobot_nav_enabled=False)
    csgobot_ai._apply_child_env_from_ctx({"config": cfg}, child_env)
    assert "CSGOBOT_NAV" not in child_env


@patch(
    "modules.combat.csgobot_ai.check_nav_preflight",
    return_value=(True, {"pack_version": "1.2.0", "goals": ["mid"]}),
)
def test_nav_env_summary_ok(_mock: object) -> None:
    from config.schema import AppConfig
    from modules.combat import csgobot_ai

    cfg = AppConfig(csgobot_nav_enabled=True, csgobot_nav_pack="dust2_dm")
    line = csgobot_ai._nav_env_summary({"config": cfg})
    assert line is not None
    assert "dust2_dm" in line
    assert "1.2.0" in line


@patch(
    "modules.combat.csgobot_ai.check_nav_preflight",
    return_value=(False, {"errors": ["pack missing"]}),
)
def test_nav_env_summary_fail(_mock: object) -> None:
    from config.schema import AppConfig
    from modules.combat import csgobot_ai

    cfg = AppConfig(csgobot_nav_enabled=True)
    line = csgobot_ai._nav_env_summary({"config": cfg})
    assert line is not None
    assert "preflight failed" in line
