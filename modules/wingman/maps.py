"""Wingman map identity and profile selection, separate from Deathmatch.

A map is enabled only when its profile is explicitly release-ready. Merely
adding radar images must not start input with another map's geometry.
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
MAP_FOLDERS = {"de_inferno": "inferno", "de_nuke": "nuke"}


def profile_folder(map_id):
    try: return ROOT / "resources" / "wingman" / MAP_FOLDERS[map_id]
    except KeyError: raise ValueError("Unsupported Wingman map: " + str(map_id)) from None


def map_ready(map_id):
    if map_id not in MAP_FOLDERS:return False
    if map_id == "de_inferno":return True
    folder=profile_folder(map_id)
    try:
        data=json.loads((folder / "navigation.json").read_text())
        return (data.get("map_id")==map_id and data.get("runtime_ready") is True
                and all((folder / name).is_file() for name in ("walkable.png","objectives.json","ingress.json"))
                and bool(data.get("required_assets"))
                and all((ROOT / name).resolve().is_relative_to(ROOT.resolve()) and (ROOT / name).is_file()
                        for name in data["required_assets"]))
    except (OSError,ValueError):return False
