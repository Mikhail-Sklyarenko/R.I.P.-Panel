"""Pick the best minimap entry waypoint toward a goal (PR-N3)."""

from __future__ import annotations

from nav.coords import dist_norm
from nav.pack import NavEntry, NavGoal
from nav.pose import PoseResult


def pick_nearest_entry(
    pose: PoseResult,
    entries: tuple[NavEntry, ...],
    *,
    team: str = "any",
) -> NavEntry | None:
    """Return the closest entry for the current pose (optionally filtered by team)."""
    if not entries or not pose.valid:
        return None

    team_key = team.strip().lower()
    candidates = [
        entry
        for entry in entries
        if entry.team in ("any", team_key)
    ]
    if not candidates:
        candidates = list(entries)

    return min(
        candidates,
        key=lambda entry: dist_norm(
            pose.x_norm,
            pose.y_norm,
            entry.x,
            entry.y,
        ),
    )


def should_use_entry(
    pose: PoseResult,
    goal: NavGoal,
    entries: tuple[NavEntry, ...],
    *,
    direct_goal_dist: float,
) -> bool:
    """Skip entries when already close enough to walk directly to the goal."""
    if not entries or not pose.valid:
        return False
    dist = dist_norm(pose.x_norm, pose.y_norm, goal.x, goal.y)
    return dist > direct_goal_dist


def entry_as_goal(entry: NavEntry) -> NavGoal:
    return NavGoal(
        id=entry.id,
        x=entry.x,
        y=entry.y,
        arrive_radius=entry.arrive_radius,
    )
