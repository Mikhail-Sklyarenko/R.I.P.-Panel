"""Map-frame pose for CS2 centered radar (seed + dead reckoning).

Product reality: the HUD keeps the player icon at the radar center and rotates
the map under it. Absolute cyan-blob XY is wrong. Matching live HUD pixels to
``radar.png`` is unreliable (domain gap).

What *is* reliable:
- Icon lock → we are alive on the radar
- Commanded mouse yaw → world heading deltas
- W + annular radar flow → forward motion in the body frame
- Pack landmarks / entries → spawn priors and absolute goals (mid, A, …)

This tracker seeds a map pose at a spawn facing the active goal, then integrates
commanded motion so NavController can run classic goal-follow to concrete points.
"""

from __future__ import annotations

import json
import logging
import math
import random
from dataclasses import dataclass
from typing import Optional

from nav.coords import bearing_deg, normalize_angle_deg
from nav.pack import NavGoal, NavPack
from nav.paths import resolve_map_meta_path
from nav.pose import PoseResult

# CS2 walk ≈ 250 u/s; Dust2 radar scale 4.4 → ~0.05 norm/s across the map.
WALK_SPEED_FLOW = 0.050
WALK_SPEED_BLIND = 0.024
POSE_LOST_RESEED_SEC = 0.85


@dataclass(frozen=True)
class SpawnPrior:
    id: str
    x: float
    y: float
    team: str = "any"


def load_spawn_priors(map_id: str, pack: NavPack) -> tuple[SpawnPrior, ...]:
    """Landmarks from map meta + pack entries as spawn / life-start priors."""
    priors: list[SpawnPrior] = []
    meta_path = resolve_map_meta_path(map_id)
    if meta_path.is_file():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        landmarks = data.get("landmarks") or {}
        for key, team in (
            ("t_spawn", "t"),
            ("ct_spawn", "ct"),
        ):
            raw = landmarks.get(key)
            if isinstance(raw, dict):
                priors.append(
                    SpawnPrior(
                        id=key,
                        x=float(raw.get("x", 0.5)),
                        y=float(raw.get("y", 0.5)),
                        team=team,
                    )
                )
    for entry in pack.entries:
        priors.append(
            SpawnPrior(
                id=f"entry:{entry.id}",
                x=entry.x,
                y=entry.y,
                team=entry.team,
            )
        )
    if not priors:
        priors.append(SpawnPrior(id="map_center", x=0.5, y=0.5, team="any"))
    return tuple(priors)


class WorldPoseTracker:
    """Seed + dead-reckon map pose while the HUD reports centered radar."""

    def __init__(
        self,
        pack: NavPack,
        *,
        logger: Optional[logging.Logger] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        self._pack = pack
        self._log = logger or logging.getLogger("CS2Bot.nav")
        self._rng = rng or random.Random()
        self._priors = load_spawn_priors(pack.map_id, pack)
        self._x = 0.5
        self._y = 0.5
        self._yaw = 0.0
        self._seeded = False
        self._seed_id = ""
        self._pose_lost_since: Optional[float] = None
        self._seed_index = 0
        self._escapes_since_seed = 0

    @property
    def seeded(self) -> bool:
        return self._seeded

    @property
    def seed_id(self) -> str:
        return self._seed_id

    def reset(self) -> None:
        self._seeded = False
        self._seed_id = ""
        self._pose_lost_since = None
        self._escapes_since_seed = 0

    def reload_pack(self, pack: NavPack) -> None:
        self._pack = pack
        self._priors = load_spawn_priors(pack.map_id, pack)
        self.reset()

    def _candidates(self, team: str) -> list[SpawnPrior]:
        team = (team or "any").strip().lower()
        if team in ("t", "ct"):
            matched = [p for p in self._priors if p.team in (team, "any")]
            if matched:
                return matched
        return list(self._priors)

    def _pick_spawn(self, team: str, goal: NavGoal) -> SpawnPrior:
        cands = self._candidates(team)
        # Prefer team spawn, else prior closest to the active goal (DM variety).
        preferred = [p for p in cands if p.id.endswith("spawn") or "spawn" in p.id]
        pool = preferred or cands
        # Rotate through pool so repeated reseeds explore different lives.
        self._seed_index += 1
        idx = self._seed_index % len(pool)
        # Slight bias: among first three, pick closest to goal.
        window = pool[idx:] + pool[:idx]
        ranked = sorted(
            window[: min(3, len(window))],
            key=lambda p: (p.x - goal.x) ** 2 + (p.y - goal.y) ** 2,
        )
        return ranked[0]

    def seed(
        self,
        goal: NavGoal,
        *,
        team: str = "any",
        now: float,
        reason: str = "life_start",
    ) -> None:
        spawn = self._pick_spawn(team, goal)
        self._x = spawn.x
        self._y = spawn.y
        # Face the concrete pack goal immediately — product seek, not spin.
        self._yaw = bearing_deg(spawn.x, spawn.y, goal.x, goal.y)
        self._seeded = True
        self._seed_id = spawn.id
        self._pose_lost_since = None
        self._escapes_since_seed = 0
        self._log.info(
            "nav: world-pose seed %s (%.2f,%.2f) yaw=%.0f° -> %s [%s]",
            spawn.id,
            spawn.x,
            spawn.y,
            self._yaw,
            goal.id,
            reason,
        )

    def note_escape(self) -> None:
        self._escapes_since_seed += 1

    def maybe_reseed_after_escapes(
        self,
        goal: NavGoal,
        *,
        team: str,
        now: float,
        threshold: int = 3,
    ) -> bool:
        if self._escapes_since_seed < threshold:
            return False
        self.seed(goal, team=team, now=now, reason="escape_reseed")
        return True

    def observe_hud(
        self,
        hud: PoseResult,
        *,
        now: float,
        goal: NavGoal,
        team: str = "any",
    ) -> None:
        """Track life/death from centered icon lock; seed on life start."""
        if not hud.valid or hud.radar_mode not in ("centered", "world"):
            if self._pose_lost_since is None:
                self._pose_lost_since = now
            return

        if self._pose_lost_since is not None:
            lost_for = now - self._pose_lost_since
            self._pose_lost_since = None
            if lost_for >= POSE_LOST_RESEED_SEC or not self._seeded:
                self.seed(goal, team=team, now=now, reason="respawn")
                return

        if not self._seeded:
            self.seed(goal, team=team, now=now, reason="first_lock")

    def integrate(
        self,
        *,
        dt: float,
        yaw_delta_deg: float,
        forward: bool,
        radar_progressing: bool,
    ) -> None:
        if not self._seeded:
            return
        dt = max(0.0, min(0.12, float(dt)))
        self._yaw = normalize_angle_deg(self._yaw + float(yaw_delta_deg))
        if not forward or dt <= 0.0:
            return
        speed = WALK_SPEED_FLOW if radar_progressing else WALK_SPEED_BLIND
        rad = math.radians(self._yaw)
        self._x = max(0.04, min(0.96, self._x + speed * dt * math.cos(rad)))
        self._y = max(0.04, min(0.96, self._y + speed * dt * math.sin(rad)))

    def face_point(self, x: float, y: float) -> None:
        """Reorient yaw toward a map point without teleporting XY."""
        if not self._seeded:
            return
        self._yaw = bearing_deg(self._x, self._y, x, y)

    def to_pose(self, hud: PoseResult) -> PoseResult:
        """Map-frame pose for goal following; invalid if HUD icon lost."""
        if not hud.valid:
            return PoseResult.invalid()
        if not self._seeded:
            return PoseResult(
                x_norm=hud.x_norm,
                y_norm=hud.y_norm,
                yaw_deg=hud.yaw_deg,
                confidence=hud.confidence,
                valid=True,
                blob_area_px=hud.blob_area_px,
                radar_mode="centered",
            )
        return PoseResult(
            x_norm=float(self._x),
            y_norm=float(self._y),
            yaw_deg=float(self._yaw),
            confidence=max(hud.confidence, 0.55),
            valid=True,
            blob_area_px=hud.blob_area_px,
            radar_mode="world",
        )
