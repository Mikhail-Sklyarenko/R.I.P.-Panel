"""Turn toward goal bearing and decide forward / strafe."""

from __future__ import annotations

import random
from dataclasses import dataclass

from aiming.fov_mouse import FOVMouseMovement
from nav.coords import bearing_deg, dist_norm, normalize_angle_deg
from nav.pack import HumanizeConfig, NavGoal
from nav.pose import PoseResult


@dataclass(frozen=True)
class FollowPlan:
    yaw_error_deg: float
    turn_step_deg: float
    dist_to_goal: float
    forward: bool


@dataclass(frozen=True)
class GoalFollowOutput:
    mouse_dx: int
    mouse_dy: int
    forward: bool
    strafe: str | None
    yaw_error_deg: float
    dist_to_goal: float


def compute_follow_plan(
    pose: PoseResult,
    goal: NavGoal,
    humanize: HumanizeConfig,
    *,
    dt_sec: float,
    wobble_bias_deg: float = 0.0,
    allow_forward: bool = True,
    turn_rate_deg_per_sec: float | None = None,
) -> FollowPlan:
    dist = dist_norm(pose.x_norm, pose.y_norm, goal.x, goal.y)
    target_bearing = bearing_deg(
        pose.x_norm, pose.y_norm, goal.x, goal.y,
    ) + wobble_bias_deg
    yaw_error = normalize_angle_deg(target_bearing - pose.yaw_deg)

    rate = (
        turn_rate_deg_per_sec
        if turn_rate_deg_per_sec is not None
        else humanize.turn_rate_deg_per_sec
    )
    max_turn = rate * max(dt_sec, 1.0 / 120.0)
    turn_step = max(-max_turn, min(max_turn, yaw_error))
    forward = (
        allow_forward
        and abs(yaw_error) <= humanize.forward_max_yaw_deg
    )

    return FollowPlan(
        yaw_error_deg=yaw_error,
        turn_step_deg=turn_step,
        dist_to_goal=dist,
        forward=forward,
    )


def compute_goal_follow(
    pose: PoseResult,
    goal: NavGoal,
    humanize: HumanizeConfig,
    fov_mouse: FOVMouseMovement,
    *,
    dt_sec: float,
    wobble_bias_deg: float = 0.0,
    allow_forward: bool = True,
) -> GoalFollowOutput:
    plan = compute_follow_plan(
        pose,
        goal,
        humanize,
        dt_sec=dt_sec,
        wobble_bias_deg=wobble_bias_deg,
        allow_forward=allow_forward,
    )
    mouse_dx, mouse_dy = fov_mouse.angle_to_mouse(plan.turn_step_deg, 0.0)
    return GoalFollowOutput(
        mouse_dx=mouse_dx,
        mouse_dy=mouse_dy,
        forward=plan.forward,
        strafe=None,
        yaw_error_deg=plan.yaw_error_deg,
        dist_to_goal=plan.dist_to_goal,
    )


def random_wobble_deg(humanize: HumanizeConfig) -> float:
    span = humanize.path_wobble_deg
    return random.uniform(-span, span)


def should_micro_pause(humanize: HumanizeConfig) -> bool:
    return random.random() < humanize.micro_pause_chance
