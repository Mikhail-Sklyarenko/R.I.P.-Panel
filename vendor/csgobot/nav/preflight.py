"""Preflight checks for minimap navigation assets (PR-N5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nav.calibration import load_calibration
from nav.pack import load_nav_pack
from nav.pack_resolve import is_auto_pack, iter_preflight_pack_ids
from nav.paths import (
    resolve_calibration_path,
    resolve_map_meta_path,
    resolve_map_radar_path,
    resolve_nav_pack_path,
    resolve_nav_root,
)


def run_nav_preflight(
    *,
    pack_id: str = "dust2_dm",
    calibration_path: str = "",
) -> dict[str, Any]:
    """
    Validate nav assets before enabling movement.

    When pack_id is ``auto``, every registered map pack is checked.
  """
    if is_auto_pack(pack_id):
        return _run_nav_preflight_auto(calibration_path=calibration_path)
    return _run_nav_preflight_one(pack_id=pack_id, calibration_path=calibration_path)


def _run_nav_preflight_auto(*, calibration_path: str = "") -> dict[str, Any]:
    pack_ids = iter_preflight_pack_ids("auto")
    results = [
        _run_nav_preflight_one(pack_id=pid, calibration_path=calibration_path)
        for pid in pack_ids
    ]
    errors: list[str] = []
    warnings: list[str] = []
    packs_ok: list[str] = []
    pack_versions: dict[str, str] = {}
    for pid, result in zip(pack_ids, results):
        errors.extend(result.get("errors") or [])
        warnings.extend(result.get("warnings") or [])
        if result.get("ok"):
            packs_ok.append(pid)
            if result.get("pack_version"):
                pack_versions[pid] = str(result["pack_version"])
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "pack_id": "auto",
        "pack_version": "",
        "pack_versions": pack_versions,
        "packs_ok": packs_ok,
        "map_id": "",
        "strategy": "auto",
        "goals": [],
        "calibration": results[0].get("calibration", "") if results else "",
        "pack_path": "",
    }


def _run_nav_preflight_one(
    *,
    pack_id: str = "dust2_dm",
    calibration_path: str = "",
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    pack_version = ""
    map_id = ""
    strategy = ""
    goal_ids: list[str] = []

    nav_root = resolve_nav_root()
    manifest_path = nav_root / "manifest.json"
    if not manifest_path.is_file():
        warnings.append("resources/nav/manifest.json missing")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("never_train") is not True:
                warnings.append("nav manifest: never_train should be true")
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"nav manifest unreadable: {exc}")

    cal_path = resolve_calibration_path(calibration_path)
    if not cal_path.is_file():
        errors.append(f"calibration missing: {cal_path.name}")
    else:
        try:
            cal = load_calibration(cal_path)
            if cal.resolution != (1280, 720):
                warnings.append(
                    f"calibration resolution {cal.resolution} != 1280x720"
                )
            rect = cal.minimap.rect
            if rect.w < 100 or rect.h < 100:
                errors.append(
                    f"minimap rect too small: {rect.w}x{rect.h}px"
                )
        except Exception as exc:
            errors.append(f"calibration invalid: {exc}")

    pack_path = resolve_nav_pack_path(pack_id)
    if not pack_path.is_file():
        errors.append(f"nav pack missing: {pack_path.name}")
    else:
        try:
            pack = load_nav_pack(pack_path)
            pack_version = pack.version
            map_id = pack.map_id
            strategy = pack.strategy
            goal_ids = [g.id for g in pack.goals]
            if not pack.goals:
                errors.append("nav pack has no goals")
            meta_path = resolve_map_meta_path(pack.map_id)
            radar_path = resolve_map_radar_path(pack.map_id)
            if not meta_path.is_file():
                errors.append(f"map meta missing: {pack.map_id}")
            if not radar_path.is_file():
                errors.append(f"map radar missing: {pack.map_id}")
            elif radar_path.stat().st_size < 1024:
                warnings.append(f"map radar suspiciously small: {radar_path.name}")
        except Exception as exc:
            errors.append(f"nav pack invalid: {exc}")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "pack_id": pack_id,
        "pack_version": pack_version,
        "map_id": map_id,
        "strategy": strategy,
        "goals": goal_ids,
        "calibration": str(cal_path) if cal_path.is_file() else "",
        "pack_path": str(pack_path) if pack_path.is_file() else "",
    }
