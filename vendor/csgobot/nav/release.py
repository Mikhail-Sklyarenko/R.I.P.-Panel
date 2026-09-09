"""Runtime identity and resource readiness shared by logs and acceptance tools."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nav.paths import resolve_visual_profile_file

ENGINE = "visual-nav-mvp-1"


def identity(map_id):
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parent
    for path in sorted(root.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    for path in (root.parent / "main.py",):
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
    for path in sorted(profile_files):
        profile.update(path.name.encode())
        profile.update(path.read_bytes())
    return {"engine": ENGINE, "code_sha256": digest.hexdigest(),
            "profile_sha256": profile.hexdigest() if profile_files else None,
            "profile_path": str(resolve_visual_profile_file(map_id, "navigation.json").parent)}
