"""Resolve nav pack id from map script or panel config (PR-N6)."""

from __future__ import annotations

from nav.paths import resolve_nav_pack_path

# Map script id (patrol / map_detect) → nav pack id.
NAV_PACK_BY_SCRIPT: dict[str, str] = {
    "dust2": "dust2_dm",
    "mirage": "mirage_dm",
    "generic_dm": "generic_dm",
}

AUTO_PACK_IDS = frozenset({"", "auto"})


def is_auto_pack(pack_id: str) -> bool:
    return pack_id.strip().lower() in AUTO_PACK_IDS


def nav_pack_for_script(script_id: str, explicit_pack: str = "auto") -> str | None:
    """Return nav pack id for a map script, or None when no pack exists."""
    if not is_auto_pack(explicit_pack):
        return explicit_pack.strip()
    return NAV_PACK_BY_SCRIPT.get(script_id.strip().lower())


def resolve_initial_nav_pack_id(
    *,
    explicit_pack: str,
    patrol_script: str,
    default_pack: str = "dust2_dm",
) -> str:
    """Pick starting pack before map_detect confirms (auto → patrol script hint)."""
    if not is_auto_pack(explicit_pack):
        return explicit_pack.strip() or default_pack
    hinted = NAV_PACK_BY_SCRIPT.get(patrol_script.strip().lower())
    return hinted or default_pack


def iter_preflight_pack_ids(explicit_pack: str) -> tuple[str, ...]:
    """Pack ids to validate in preflight (auto checks every registered pack)."""
    if is_auto_pack(explicit_pack):
        return tuple(sorted(set(NAV_PACK_BY_SCRIPT.values())))
    pack = explicit_pack.strip() or "dust2_dm"
    return (pack,)


def nav_pack_exists(pack_id: str) -> bool:
    return resolve_nav_pack_path(pack_id).is_file()
