"""Testable aim frame pipeline (smooth → lead → FOV → mouse filter → hysteresis)."""

from __future__ import annotations

from dataclasses import dataclass, field
from aiming.aim_point_smoother import AimPointSmoother, AimSmoothConfig
from aiming.dead_zone import AimHysteresis, AimHysteresisConfig
from aiming.fov_mouse import FOVMouseMovement
from aiming.mouse_filter import filter_mouse_delta
from aiming.velocity_lead import LeadConfig, LeadPredictResult, VelocityLead
from aim_tuning import adaptive_smoothing
from config import AimConfig


@dataclass
class AimFrameResult:
    raw_x: float
    raw_y: float
    aim_x: float
    aim_y: float
    pixel_distance: float
    mouse_dx: int
    mouse_dy: int
    should_move: bool
    smoothing: float
    lead: LeadPredictResult = field(
        default_factory=lambda: LeadPredictResult(0, 0, False, 0.0, False)
    )


@dataclass
class AimPipelineState:
    smoother: AimPointSmoother
    velocity_lead: VelocityLead
    hysteresis: AimHysteresis

    @classmethod
    def from_aim_config(cls, aim: AimConfig) -> AimPipelineState:
        return cls(
            smoother=AimPointSmoother(
                AimSmoothConfig(
                    enabled=aim.aim_smooth_enabled,
                    alpha=aim.aim_smooth_alpha,
                    jump_reset_px=aim.aim_smooth_jump_reset_px,
                )
            ),
            velocity_lead=VelocityLead(
                LeadConfig(
                    enabled=aim.lead_aim_enabled,
                    lead_ms=aim.lead_ms,
                    ema_alpha=aim.lead_ema_alpha,
                    max_lead_px=aim.lead_max_px,
                    variance_gate=aim.lead_variance_gate,
                    min_speed_px_s=aim.lead_min_speed_px_s,
                    max_speed_variance=aim.lead_max_speed_variance,
                )
            ),
            hysteresis=AimHysteresis(
                AimHysteresisConfig(
                    high=aim.aim_dead_zone_high,
                    low=aim.aim_dead_zone_low,
                )
            ),
        )

    def reset_trackers(self) -> None:
        self.smoother.reset()
        self.velocity_lead.reset()
        self.hysteresis.reset()


def process_aim_frame(
    *,
    raw_x: float,
    raw_y: float,
    target_distance: float,
    now: float,
    aim_config: AimConfig,
    fov_mouse: FOVMouseMovement,
    pipeline: AimPipelineState,
    fps_value: float,
) -> AimFrameResult:
    smooth_x, smooth_y = pipeline.smoother.update(raw_x, raw_y, now)
    lead = pipeline.velocity_lead.predict(smooth_x, smooth_y, now)

    smoothing = aim_config.smoothing_factor
    if aim_config.adaptive_smoothing:
        smoothing = adaptive_smoothing(
            smoothing,
            target_distance,
            fps_value,
            max_distance=float(aim_config.max_assist_distance),
        )

    aim_result = fov_mouse.get_move(lead.x, lead.y, smoothing=smoothing)
    mouse_dx, mouse_dy = filter_mouse_delta(
        aim_result.mouse_x,
        aim_result.mouse_y,
        max_delta=aim_config.mouse_max_delta,
        min_delta=aim_config.mouse_min_delta,
    )
    should_move = pipeline.hysteresis.should_move(aim_result.pixel_distance)

    return AimFrameResult(
        raw_x=raw_x,
        raw_y=raw_y,
        aim_x=lead.x,
        aim_y=lead.y,
        pixel_distance=aim_result.pixel_distance,
        mouse_dx=mouse_dx,
        mouse_dy=mouse_dy,
        should_move=should_move,
        smoothing=smoothing,
        lead=lead,
    )
