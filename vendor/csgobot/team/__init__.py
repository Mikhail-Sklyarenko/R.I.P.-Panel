"""HUD team detection for DM side sync."""

from team.hud_team_detect import (
    TeamDetectState,
    detect_team_hud,
    score_probes,
    update_team_hysteresis,
)
from team.paths import resolve_team_probes_path
from team.probes import ColorProbe, TeamProbeSet, load_team_probes

__all__ = [
    "ColorProbe",
    "TeamDetectState",
    "TeamProbeSet",
    "detect_team_hud",
    "load_team_probes",
    "resolve_team_probes_path",
    "score_probes",
    "update_team_hysteresis",
]
