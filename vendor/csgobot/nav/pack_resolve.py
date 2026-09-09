"""Resolve nav pack id from map script or panel config (PR-N6 + product fix)."""

from __future__ import annotations

from nav.paths import resolve_nav_pack_path

# Map script id (patrol / map_detect) → nav pack id.
NAV_PACK_BY_SCRIPT: dict[str, str] = {
    "dust2": "dust2_dm",
    "mirage": "mirage_dm",
    "generic_dm": "generic_dm",
}

# Placeholder scripts mean "map unknown yet" — not a real DM layout pack.
PLACEHOLDER_SCRIPTS = frozenset({"", "generic_dm", "unknown"})

AUTO_PACK_IDS = frozenset({"", "auto"})

# Most common farm map when HUD detect has not confirmed yet.
PRODUCT_DEFAULT_PACK = "dust2_dm"


def is_auto_pack(pack_id: str) -> bool:
    return pack_id.strip().lower() in AUTO_PACK_IDS


def measured_runtime_pack(pack_id: str, explicit_pack: str) -> str:
    """Auto Dust2 uses the shipped measured route; explicit choices stay explicit."""
    if pack_id == "dust2_dm" and is_auto_pack(explicit_pack):
        return "dust2_visual_mvp"
    return pack_id


def is_placeholder_script(script_id: str) -> bool:
    return script_id.strip().lower() in PLACEHOLDER_SCRIPTS


def nav_pack_for_script(script_id: str, explicit_pack: str = "auto") -> str | None:
    """Return nav pack id for a map script, or None when no pack exists."""
    if not is_auto_pack(explicit_pack):
        return explicit_pack.strip()
    return NAV_PACK_BY_SCRIPT.get(script_id.strip().lower())


def resolve_initial_nav_pack_id(
    *,
    explicit_pack: str,
    patrol_script: str,
    default_pack: str = PRODUCT_DEFAULT_PACK,
) -> str:
    """
    Pick starting pack before map_detect confirms.

    Product rule: ``generic_dm`` patrol is a placeholder (unknown map), not a
    real layout. Prefer ``dust2_dm`` so Dust2 farms work immediately; map_detect
    hot-swaps to mirage/dust2 when HUD confirms.
    """
    if not is_auto_pack(explicit_pack):
        return explicit_pack.strip() or default_pack
    hinted = NAV_PACK_BY_SCRIPT.get(patrol_script.strip().lower())
    if hinted is None or is_placeholder_script(patrol_script):
        return default_pack
    return hinted


def should_fail_open_to_default(
    *,
    explicit_pack: str,
    active_pack_id: str,
    confirmed_script: str,
    map_locked: bool,
) -> bool:
    """True when auto mode is stuck on placeholder pack without a real map lock."""
    if not is_auto_pack(explicit_pack):
        return False
    if map_locked and not is_placeholder_script(confirmed_script):
        return False
    if active_pack_id != "generic_dm":
        return False
    return is_placeholder_script(confirmed_script)


def iter_preflight_pack_ids(explicit_pack: str) -> tuple[str, ...]:
    """Pack ids to validate in preflight (auto checks every registered pack)."""
    if is_auto_pack(explicit_pack):
        return tuple(sorted(set(NAV_PACK_BY_SCRIPT.values())))
    pack = explicit_pack.strip() or PRODUCT_DEFAULT_PACK
    return (pack,)


def nav_pack_exists(pack_id: str) -> bool:
    return resolve_nav_pack_path(pack_id).is_file()
