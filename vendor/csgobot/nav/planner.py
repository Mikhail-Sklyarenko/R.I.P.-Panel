"""Graph path planner over pack waypoints (turn before walls)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from nav.coords import dist_norm
from nav.pack import NavGoal


@dataclass(frozen=True)
class NavWaypoint:
    id: str
    x: float
    y: float
    arrive_radius: float = 0.055


@dataclass(frozen=True)
class PathPlan:
    waypoint_ids: tuple[str, ...]
    goals: tuple[NavGoal, ...]


def _as_goal(wp: NavWaypoint) -> NavGoal:
    return NavGoal(id=wp.id, x=wp.x, y=wp.y, arrive_radius=wp.arrive_radius)


def plan_path(
    start_x: float,
    start_y: float,
    goal: NavGoal,
    waypoints: tuple[NavWaypoint, ...],
    edges: tuple[tuple[str, str], ...],
) -> PathPlan:
    """Shortest hop path on an undirected waypoint graph to ``goal``.

    If the graph is empty or disconnected, returns a direct plan to ``goal``.
    """
    if not waypoints or not edges:
        return PathPlan(waypoint_ids=(goal.id,), goals=(goal,))

    by_id = {wp.id: wp for wp in waypoints}
    # Virtual nodes for start (nearest wp) and goal (goal itself or nearest)
    nearest_start = min(
        waypoints, key=lambda wp: dist_norm(start_x, start_y, wp.x, wp.y)
    )
    # Attach goal as a node if not present
    goal_node = goal.id
    if goal_node not in by_id:
        by_id[goal_node] = NavWaypoint(
            id=goal_node, x=goal.x, y=goal.y, arrive_radius=goal.arrive_radius
        )

    adj: dict[str, list[str]] = {k: [] for k in by_id}
    for a, b in edges:
        if a in adj and b in adj:
            adj[a].append(b)
            adj[b].append(a)
    # Connect goal to its nearest graph waypoint if it wasn't linked
    if goal_node not in {e[0] for e in edges} | {e[1] for e in edges}:
        near_g = min(
            waypoints, key=lambda wp: dist_norm(goal.x, goal.y, wp.x, wp.y)
        )
        adj.setdefault(near_g.id, []).append(goal_node)
        adj.setdefault(goal_node, []).append(near_g.id)

    start_id = nearest_start.id
    # Dijkstra
    dist = {k: math.inf for k in by_id}
    prev: dict[str, Optional[str]] = {k: None for k in by_id}
    dist[start_id] = 0.0
    remaining = set(by_id)
    while remaining:
        u = min(remaining, key=lambda k: dist[k])
        remaining.remove(u)
        if u == goal_node:
            break
        if dist[u] == math.inf:
            break
        for v in adj.get(u, []):
            wu = by_id[u]
            wv = by_id[v]
            alt = dist[u] + dist_norm(wu.x, wu.y, wv.x, wv.y)
            if alt < dist[v]:
                dist[v] = alt
                prev[v] = u

    if dist.get(goal_node, math.inf) == math.inf:
        return PathPlan(waypoint_ids=(goal.id,), goals=(goal,))

    chain: list[str] = []
    cur: Optional[str] = goal_node
    while cur is not None:
        chain.append(cur)
        cur = prev.get(cur)
    chain.reverse()
    # Drop start if we're already inside its arrive radius
    if chain and chain[0] == start_id:
        if dist_norm(start_x, start_y, by_id[start_id].x, by_id[start_id].y) <= by_id[
            start_id
        ].arrive_radius:
            chain = chain[1:] or chain

    goals = tuple(
        goal if wid == goal.id else _as_goal(by_id[wid]) for wid in chain
    )
    return PathPlan(waypoint_ids=tuple(chain), goals=goals)
