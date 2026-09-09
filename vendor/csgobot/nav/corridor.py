"""Corridor scripts — place-triggered walk stages (not continuous GPS chase).

Product contract: a place label picks a short script of face→walk bursts.
We never invent mid-map XY motion; Safe-W forbids holding W into walls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CorridorStep:
    """One stage: face a landmark, walk briefly, advance on place or timeout."""

    face_id: str
    walk_sec: float
    advance_places: tuple[str, ...]


@dataclass(frozen=True)
class CorridorScript:
    id: str
    start_places: tuple[str, ...]
    goal_id: str
    steps: tuple[CorridorStep, ...]


# Dust2 DM — spawn/corridor → mid (and A). Tuned for place-label stages.
DUST2_CORRIDORS: tuple[CorridorScript, ...] = (
    CorridorScript(
        id="ct_spawn_to_mid",
        start_places=("ct_spawn", "near_a", "bombsite_a"),
        goal_id="mid",
        steps=(
            CorridorStep("short", 3.5, ("short", "ledge", "mid_upper", "a_ramp")),
            CorridorStep("mid", 5.0, ("mid", "mid_doors", "mid_upper", "pit")),
        ),
    ),
    CorridorScript(
        id="a_side_to_mid",
        start_places=("a_ramp", "under_a", "long_a", "short", "ledge"),
        goal_id="mid",
        steps=(
            CorridorStep("mid", 4.5, ("mid", "mid_upper", "mid_doors", "short")),
        ),
    ),
    CorridorScript(
        id="t_spawn_to_mid",
        start_places=("t_spawn", "t_ramp"),
        goal_id="mid",
        steps=(
            CorridorStep("mid", 4.0, ("mid", "mid_doors", "pit", "long", "t_ramp")),
            CorridorStep("mid", 4.0, ("mid", "mid_doors", "mid_upper")),
        ),
    ),
    CorridorScript(
        id="long_to_mid",
        start_places=("long", "long_doors", "pit"),
        goal_id="mid",
        steps=(
            CorridorStep("mid", 4.0, ("mid", "mid_doors", "pit")),
        ),
    ),
    CorridorScript(
        id="tunnel_to_mid",
        start_places=(
            "tunnel",
            "tunnel_stairs",
            "tunnel_upper",
            "outside_tunnel",
            "b_doors",
            "bombsite_b",
        ),
        goal_id="mid",
        steps=(
            CorridorStep(
                "outside_tunnel",
                3.0,
                ("outside_tunnel", "tunnel", "mid", "mid_doors"),
            ),
            CorridorStep("mid", 4.5, ("mid", "mid_doors", "pit", "outside_tunnel")),
        ),
    ),
    CorridorScript(
        id="mid_hold",
        start_places=("mid", "mid_upper", "mid_doors"),
        goal_id="mid",
        steps=(
            CorridorStep("mid", 2.0, ("mid", "mid_upper", "mid_doors")),
        ),
    ),
    CorridorScript(
        id="mid_to_a",
        start_places=("mid", "mid_upper", "short", "ledge"),
        goal_id="bombsite_a",
        steps=(
            CorridorStep("short", 3.0, ("short", "a_ramp", "ledge", "near_a")),
            CorridorStep(
                "bombsite_a",
                4.0,
                ("bombsite_a", "near_a", "a_ramp", "under_a"),
            ),
        ),
    ),
)


def pick_corridor(
    place_id: Optional[str],
    goal_id: str,
    *,
    scripts: tuple[CorridorScript, ...] = DUST2_CORRIDORS,
) -> Optional[CorridorScript]:
    if not place_id:
        return None
    pid = place_id.strip()
    goal = (goal_id or "mid").strip()
    # Prefer scripts whose goal matches route goal.
    for script in scripts:
        if script.goal_id == goal and pid in script.start_places:
            return script
    for script in scripts:
        if pid in script.start_places:
            return script
    return None


def build_edge_neighbors(edges: tuple[tuple[str, str], ...]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for a, b in edges:
        out.setdefault(a, set()).add(b)
        out.setdefault(b, set()).add(a)
    return out
