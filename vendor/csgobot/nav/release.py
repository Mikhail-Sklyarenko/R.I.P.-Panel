"""Runtime identity and resource readiness shared by logs and acceptance tools."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nav.paths import resolve_visual_profile_file

ENGINE = "visual-nav-multimap-22"


def identity(map_id):
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parent
    for path in sorted(root.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    runtime_files = [root.parent / name for name in ("main.py", "run.py", "config.py")]
    runtime_files.append(root.parent / "tools" / "preflight.py")
    runtime_files.extend((root.parent / "aiming").glob("*.py"))
    runtime_files.extend((root.parent / "map").glob("*.py"))
    for path in sorted(runtime_files):
        digest.update(str(path.relative_to(root.parent)).encode())
        digest.update(path.read_bytes())
    profile = hashlib.sha256()
    profile_files = []
    for name in ("atlas.json", "navigation.json"):
        path = resolve_visual_profile_file(map_id, name)
        if path.is_file():
            profile_files.append(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            if name == "atlas.json":
                for ref in data.get("references", []):
                    image = (path.parent / ref["image"]).resolve()
                    if not image.is_relative_to(path.parent.resolve()):
                        raise ValueError("Atlas image outside its profile")
                    profile_files.append(image)
            else:
                profile_files.append(path.parent / "walkable.png")
    traversal = resolve_visual_profile_file(map_id, 'traversal.json')
    if traversal.is_file():
        profile_files.append(traversal)
    if map_id == 'de_dust2':
        from nav.paths import resolve_nav_root
        expanded = resolve_nav_root()/'experimental/de_dust2'
        profile_files.extend(expanded/name for name in ('navigation.json','walkable.png'))
    if map_id in ('de_mirage','de_cache'):
        layers=resolve_visual_profile_file(map_id,'layers.json')
        profile_files.append(layers)
        data=json.loads(layers.read_text(encoding='utf-8'))
        profile_files.extend(layers.parent/name for name in data['layers'].values())
        profile_files.extend(layers.parent/item['image'] for item in data['labels'])
    if map_id == 'de_cache':
        from nav.paths import resolve_map_radar_path
        profile_files.append(resolve_map_radar_path(map_id))
    if map_id == 'de_vertigo':
        from nav.paths import resolve_map_radar_path
        layers = resolve_visual_profile_file(map_id,'layers.json')
        profile_files.append(layers)
        for layer_map in ('de_vertigo','de_vertigo_lower'):
            profile_files.append(resolve_map_radar_path(layer_map))
        for name in ('atlas.json','navigation.json','walkable.png'):
            path = resolve_visual_profile_file('de_vertigo_lower',name)
            profile_files.append(path)
            if name == 'atlas.json':
                for ref in json.loads(path.read_text(encoding='utf-8'))['references']:
                    image = (path.parent/ref['image']).resolve()
                    if not image.is_relative_to(path.parent.resolve()):
                        raise ValueError('Atlas image outside its profile')
                    profile_files.append(image)
    for path in sorted(profile_files):
        profile.update(path.name.encode())
        profile.update(path.read_bytes())
    return {"engine": ENGINE, "code_sha256": digest.hexdigest(),
            "profile_sha256": profile.hexdigest() if profile_files else None,
            "profile_path": str(resolve_visual_profile_file(map_id, "navigation.json").parent)}
