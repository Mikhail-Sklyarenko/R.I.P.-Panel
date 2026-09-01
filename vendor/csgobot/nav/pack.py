"""Navigation pack schema (goal, entries, routing, humanize, fallback, stuck)."""



from __future__ import annotations



from dataclasses import dataclass

from pathlib import Path

from typing import Any



import yaml





class NavPackLoadError(ValueError):

    pass





@dataclass(frozen=True)

class NavGoal:

    id: str

    x: float

    y: float

    arrive_radius: float





@dataclass(frozen=True)

class NavEntry:

    id: str

    x: float

    y: float

    arrive_radius: float

    team: str = "any"





@dataclass(frozen=True)

class RouteConfig:

    mode: str

    dwell_at_goal_sec: float

    direct_goal_dist: float





@dataclass(frozen=True)

class AtGoalConfig:

    mode: str

    radius: float

    wander_sec_min: float

    wander_sec_max: float





@dataclass(frozen=True)

class HumanizeConfig:

    speed_jitter: float

    micro_pause_chance: float

    micro_pause_sec_min: float

    micro_pause_sec_max: float

    turn_rate_deg_per_sec: float

    path_wobble_deg: float

    forward_max_yaw_deg: float

    turn_smooth_alpha: float

    wobble_refresh_sec: float

    forward_jitter_chance: float

    forward_jitter_sec_min: float

    forward_jitter_sec_max: float

    look_yield_turn: bool





@dataclass(frozen=True)

class FallbackConfig:

    macro_script: str

    macro_sec: float

    retry_nav_after_macro: bool = True





@dataclass(frozen=True)

class StuckConfig:

    progress_timeout_sec: float

    min_progress_norm: float

    escape_angles_deg: tuple[float, ...]

    escape_duration_sec: float





@dataclass(frozen=True)

class NavPack:

    pack_id: str

    map_id: str

    mode: str

    version: str

    strategy: str

    goal: NavGoal

    goals: tuple[NavGoal, ...]

    entries: tuple[NavEntry, ...]

    route: RouteConfig

    at_goal: AtGoalConfig

    humanize: HumanizeConfig

    fallback: FallbackConfig

    stuck: StuckConfig





def _parse_goal(raw: dict[str, Any], *, default_id: str = "goal") -> NavGoal:

    return NavGoal(

        id=str(raw.get("id", default_id)),

        x=float(raw.get("x", 0.5)),

        y=float(raw.get("y", 0.5)),

        arrive_radius=float(raw.get("arrive_radius", 0.06)),

    )





def _parse_entry(raw: dict[str, Any]) -> NavEntry:

    if not isinstance(raw, dict):

        raise NavPackLoadError("each entry must be a mapping")

    entry_id = str(raw.get("id", "")).strip()

    if not entry_id:

        raise NavPackLoadError("entry.id is required")

    return NavEntry(

        id=entry_id,

        x=float(raw.get("x", 0.5)),

        y=float(raw.get("y", 0.5)),

        arrive_radius=float(raw.get("arrive_radius", 0.05)),

        team=str(raw.get("team", "any")).strip().lower() or "any",

    )





def parse_nav_pack_data(data: dict[str, Any]) -> NavPack:

    meta = data.get("meta") or {}

    pack_id = str(meta.get("pack_id", ""))

    map_id = str(meta.get("map_id", ""))

    if not pack_id or not map_id:

        raise NavPackLoadError("meta.pack_id and meta.map_id are required")



    goal_raw = data.get("goal") or {}

    goal = _parse_goal(goal_raw)



    goals_raw = data.get("goals") or []

    if goals_raw:

        goals = tuple(_parse_goal(item) for item in goals_raw)

    else:

        goals = (goal,)



    entries_raw = data.get("entries") or []

    entries = tuple(_parse_entry(item) for item in entries_raw)



    route_raw = data.get("routing") or data.get("entry_routing") or {}

    route = RouteConfig(

        mode=str(route_raw.get("mode", "single")),

        dwell_at_goal_sec=float(route_raw.get("dwell_at_goal_sec", 30.0)),

        direct_goal_dist=float(route_raw.get("direct_goal_dist", 0.12)),

    )



    at_raw = data.get("at_goal") or {}

    at_goal = AtGoalConfig(

        mode=str(at_raw.get("mode", "wander")),

        radius=float(at_raw.get("radius", 0.08)),

        wander_sec_min=float(at_raw.get("wander_sec_min", 1.5)),

        wander_sec_max=float(at_raw.get("wander_sec_max", 4.0)),

    )



    hum_raw = data.get("humanize") or {}

    humanize = HumanizeConfig(

        speed_jitter=float(hum_raw.get("speed_jitter", 0.12)),

        micro_pause_chance=float(hum_raw.get("micro_pause_chance", 0.03)),

        micro_pause_sec_min=float(hum_raw.get("micro_pause_sec_min", 0.1)),

        micro_pause_sec_max=float(hum_raw.get("micro_pause_sec_max", 0.35)),

        turn_rate_deg_per_sec=float(hum_raw.get("turn_rate_deg_per_sec", 90.0)),

        path_wobble_deg=float(hum_raw.get("path_wobble_deg", 4.0)),

        forward_max_yaw_deg=float(hum_raw.get("forward_max_yaw_deg", 22.0)),

        turn_smooth_alpha=float(hum_raw.get("turn_smooth_alpha", 0.42)),

        wobble_refresh_sec=float(hum_raw.get("wobble_refresh_sec", 0.85)),

        forward_jitter_chance=float(hum_raw.get("forward_jitter_chance", 0.04)),

        forward_jitter_sec_min=float(hum_raw.get("forward_jitter_sec_min", 0.05)),

        forward_jitter_sec_max=float(hum_raw.get("forward_jitter_sec_max", 0.14)),

        look_yield_turn=bool(hum_raw.get("look_yield_turn", True)),

    )



    fb_raw = data.get("fallback") or {}

    fallback = FallbackConfig(

        macro_script=str(fb_raw.get("macro_script", "generic_dm")),

        macro_sec=float(fb_raw.get("macro_sec", 60.0)),

        retry_nav_after_macro=bool(fb_raw.get("retry_nav_after_macro", True)),

    )



    stuck_raw = data.get("stuck") or {}

    angles_raw = stuck_raw.get("escape_angles_deg") or [30, -30, 60, -60, 90, -90]

    stuck = StuckConfig(

        progress_timeout_sec=float(stuck_raw.get("progress_timeout_sec", 3.0)),

        min_progress_norm=float(stuck_raw.get("min_progress_norm", 0.008)),

        escape_angles_deg=tuple(float(a) for a in angles_raw),

        escape_duration_sec=float(stuck_raw.get("escape_duration_sec", 0.45)),

    )



    return NavPack(

        pack_id=pack_id,

        map_id=map_id,

        mode=str(meta.get("mode", "deathmatch")),

        version=str(meta.get("version", "1.0.0")),

        strategy=str(data.get("strategy", "single_goal")),

        goal=goal,

        goals=goals,

        entries=entries,

        route=route,

        at_goal=at_goal,

        humanize=humanize,

        fallback=fallback,

        stuck=stuck,

    )





def load_nav_pack(path: Path) -> NavPack:

    if not path.is_file():

        raise NavPackLoadError(f"nav pack not found: {path}")

    with path.open(encoding="utf-8") as fh:

        data = yaml.safe_load(fh) or {}

    if not isinstance(data, dict):

        raise NavPackLoadError("nav pack root must be a mapping")

    return parse_nav_pack_data(data)

