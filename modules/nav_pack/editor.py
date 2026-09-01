"""Nav pack editor service (PR-N8) — farm overrides in data/nav_packs/."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from config.paths import get_app_root, get_nav_packs_override_dir


class NavPackEditorError(ValueError):
    pass


@dataclass(frozen=True)
class NavPackEditorView:
    pack_id: str
    map_id: str
    version: str
    strategy: str
    source: str  # bundled | override
    path: str
    goal_id: str
    goal_x: float
    goal_y: float
    goal_arrive_radius: float
    goal2_id: str
    goal2_x: float
    goal2_y: float
    goal2_arrive_radius: float
    dwell_at_goal_sec: float
    direct_goal_dist: float


def _bundled_dir() -> Path:
    return get_app_root() / "resources" / "nav" / "packs"


def _override_path(pack_id: str) -> Path:
    return get_nav_packs_override_dir() / f"{pack_id}.yaml"


def _bundled_path(pack_id: str) -> Path:
    return _bundled_dir() / f"{pack_id}.yaml"


def resolve_pack_path(pack_id: str) -> Path:
    pack_id = pack_id.strip()
    if not pack_id:
        raise NavPackEditorError("pack_id required")
    override = _override_path(pack_id)
    if override.is_file():
        return override
    bundled = _bundled_path(pack_id)
    if bundled.is_file():
        return bundled
    raise NavPackEditorError(f"pack not found: {pack_id}")


def list_pack_ids() -> list[str]:
    ids: set[str] = set()
    bundled = _bundled_dir()
    if bundled.is_dir():
        for path in bundled.glob("*.yaml"):
            ids.add(path.stem)
    override_dir = get_nav_packs_override_dir()
    if override_dir.is_dir():
        for path in override_dir.glob("*.yaml"):
            ids.add(path.stem)
    return sorted(ids)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise NavPackEditorError(f"invalid pack root: {path.name}")
    return data


def load_pack_view(pack_id: str) -> NavPackEditorView:
    path = resolve_pack_path(pack_id)
    data = _load_yaml(path)
    meta = data.get("meta") or {}
    goal = data.get("goal") or {}
    goals = data.get("goals") or []
    goal2 = goals[1] if len(goals) > 1 else {}
    routing = data.get("routing") or {}
    source = "override" if path.parent == get_nav_packs_override_dir() else "bundled"
    return NavPackEditorView(
        pack_id=str(meta.get("pack_id") or pack_id),
        map_id=str(meta.get("map_id") or ""),
        version=str(meta.get("version") or "1.0.0"),
        strategy=str(data.get("strategy") or "single_goal"),
        source=source,
        path=str(path),
        goal_id=str(goal.get("id") or "mid"),
        goal_x=float(goal.get("x", 0.5)),
        goal_y=float(goal.get("y", 0.5)),
        goal_arrive_radius=float(goal.get("arrive_radius", 0.06)),
        goal2_id=str(goal2.get("id") or ""),
        goal2_x=float(goal2.get("x", 0.5)),
        goal2_y=float(goal2.get("y", 0.5)),
        goal2_arrive_radius=float(goal2.get("arrive_radius", 0.06)),
        dwell_at_goal_sec=float(routing.get("dwell_at_goal_sec", 30.0)),
        direct_goal_dist=float(routing.get("direct_goal_dist", 0.12)),
    )


def _bump_patch_version(version: str) -> str:
    parts = str(version).split(".")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        parts[2] = str(int(parts[2]) + 1)
        return ".".join(parts)
    return version


def _validate_coords(x: float, y: float, label: str) -> None:
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise NavPackEditorError(f"{label} x/y must be 0..1")


def save_pack_override(
    pack_id: str,
    *,
    goal_x: float,
    goal_y: float,
    goal_arrive_radius: float,
    goal2_x: float | None = None,
    goal2_y: float | None = None,
    goal2_arrive_radius: float | None = None,
    dwell_at_goal_sec: float | None = None,
    direct_goal_dist: float | None = None,
) -> Path:
    _validate_coords(goal_x, goal_y, "goal")
    if goal2_x is not None and goal2_y is not None:
        _validate_coords(goal2_x, goal2_y, "goal2")
    if not (0.01 <= goal_arrive_radius <= 0.25):
        raise NavPackEditorError("goal arrive_radius must be 0.01..0.25")

    base_path = _bundled_path(pack_id)
    if not base_path.is_file():
        raise NavPackEditorError(f"bundled pack missing: {pack_id}")
    data = _load_yaml(base_path)

    goal = data.setdefault("goal", {})
    if not isinstance(goal, dict):
        raise NavPackEditorError("goal must be a mapping")
    goal["x"] = round(goal_x, 4)
    goal["y"] = round(goal_y, 4)
    goal["arrive_radius"] = round(goal_arrive_radius, 4)

    goals = data.get("goals")
    if isinstance(goals, list) and goals:
        if isinstance(goals[0], dict):
            goals[0]["x"] = goal["x"]
            goals[0]["y"] = goal["y"]
            goals[0]["arrive_radius"] = goal["arrive_radius"]
        if len(goals) > 1 and isinstance(goals[1], dict):
            if goal2_x is not None:
                goals[1]["x"] = round(goal2_x, 4)
            if goal2_y is not None:
                goals[1]["y"] = round(goal2_y, 4)
            if goal2_arrive_radius is not None:
                goals[1]["arrive_radius"] = round(goal2_arrive_radius, 4)

    routing = data.setdefault("routing", {})
    if isinstance(routing, dict):
        if dwell_at_goal_sec is not None:
            routing["dwell_at_goal_sec"] = float(dwell_at_goal_sec)
        if direct_goal_dist is not None:
            routing["direct_goal_dist"] = float(direct_goal_dist)

    meta = data.setdefault("meta", {})
    if isinstance(meta, dict):
        meta["version"] = _bump_patch_version(str(meta.get("version") or "1.0.0"))

    out_dir = get_nav_packs_override_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = _override_path(pack_id)
    out_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return out_path


def reset_pack_override(pack_id: str) -> bool:
    path = _override_path(pack_id)
    if not path.is_file():
        return False
    path.unlink()
    return True


def has_override(pack_id: str) -> bool:
    return _override_path(pack_id).is_file()
