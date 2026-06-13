"""Detect CT/T from in-combat HUD color probes with hysteresis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np

from team.probes import ColorProbe, TeamProbeSet

TeamSide = Literal["ct", "t"]


def _probe_match_rgb(
    img: np.ndarray,
    probe: ColorProbe,
) -> bool:
    h, w = img.shape[:2]
    x, y = probe.x, probe.y
    if x < 0 or y < 0 or x >= w or y >= h:
        return False
    pixel = img[y, x]
    r, g, b = int(pixel[0]), int(pixel[1]), int(pixel[2])
    tr, tg, tb = probe.rgb
    tol = probe.tolerance
    return (
        abs(r - tr) <= tol
        and abs(g - tg) <= tol
        and abs(b - tb) <= tol
    )


def score_probes(img: np.ndarray, probes: tuple[ColorProbe, ...]) -> int:
    return sum(1 for probe in probes if _probe_match_rgb(img, probe))


def detect_team_hud(
    img: np.ndarray,
    probes: TeamProbeSet,
    *,
    min_votes: int = 2,
) -> Optional[TeamSide]:
    """Return ct/t when probe voting is decisive; None if ambiguous."""
    ct_score = score_probes(img, probes.ct)
    t_score = score_probes(img, probes.t)

    if ct_score >= min_votes and ct_score > t_score:
        return "ct"
    if t_score >= min_votes and t_score > ct_score:
        return "t"
    return None


@dataclass
class TeamDetectState:
    pending_team: Optional[str] = None
    pending_count: int = 0
    confirmed_team: str = "ct"

    @classmethod
    def from_team(cls, team: str) -> TeamDetectState:
        side = team.lower()
        if side not in ("ct", "t"):
            side = "ct"
        return cls(confirmed_team=side)


def update_team_hysteresis(
    state: TeamDetectState,
    winner: Optional[TeamSide],
    *,
    confirm_frames: int,
) -> tuple[Optional[TeamSide], int]:
    """
    Apply hysteresis to a detection winner.

    Returns (new_confirmed_team_if_changed, pending_count_after_update).
    """
    if winner is None:
        state.pending_team = None
        state.pending_count = 0
        return None, 0

    if winner == state.pending_team:
        state.pending_count += 1
    else:
        state.pending_team = winner
        state.pending_count = 1

    if (
        state.pending_count >= confirm_frames
        and winner != state.confirmed_team
    ):
        state.confirmed_team = winner
        state.pending_team = None
        state.pending_count = 0
        return winner, confirm_frames

    return None, state.pending_count
