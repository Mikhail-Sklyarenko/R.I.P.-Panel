"""Deterministic round decisions; observations never directly issue OS input."""
from dataclasses import dataclass, replace
from enum import Enum
from math import isfinite


class Phase(str, Enum):
    UNKNOWN = "unknown"
    WARMUP = "warmup"
    FREEZE = "freeze"
    LIVE = "live"
    OVER = "over"
    FINISHED = "finished"


@dataclass(frozen=True)
class Observation:
    sequence: int
    observed_at: float
    match_id: str
    round_number: int
    map_id: str
    phase: Phase
    own_player: bool
    alive: bool
    team: str
    money: int | None = None
    buy_allowed: bool = False
    bomb: str = "unknown"  # carried_self, carried_other, dropped, planted, defused, exploded
    connected: bool = True


@dataclass(frozen=True)
class Decision:
    state: str
    release_inputs: bool
    navigation: bool = False
    combat: bool = False
    enemy_team: str | None = None
    objective: str | None = None
    buy_key: str | None = None
    reason: str = ""
    preserve_interaction: bool = False


class RoundEngine:
    def __init__(self, *, max_age=0.5):
        self.max_age = max_age
        self.last_sequence = -1
        self.last_timestamp = float("-inf")
        self.round_key = None
        self.buy_attempted = set()
        self.epoch = 0
        self.match_id = None
        self.finished = False
        self.closed_rounds = set()

    def update_with_visual(self, observation, evidence, *, now):
        from .visual import guard_decision
        if not 0 <= now-evidence.observed_at <= .5 or evidence.reason == "uncalibrated_resolution":
            return guard_decision(Decision("waiting", True), evidence, now=now)
        # Commit terminal evidence, so the next unrecognized frame cannot revive a round.
        if evidence.state == "finished":
            observation = replace(observation, phase=Phase.FINISHED)
        elif evidence.state == "round_over" and observation.phase != Phase.FREEZE:
            observation = replace(observation, phase=Phase.OVER)
        decision = self.update(observation, now=now)
        return guard_decision(decision, evidence, now=now)

    def update(self, observation: Observation, *, now: float) -> Decision:
        o = observation
        if (o.sequence <= self.last_sequence or not isfinite(o.observed_at)
                or not isfinite(now) or o.observed_at < self.last_timestamp
                or not 0 <= now - o.observed_at <= self.max_age):
            return Decision("waiting", True, reason="stale_or_out_of_order_observation")
        self.last_sequence, self.last_timestamp = o.sequence, o.observed_at
        if not o.connected or not o.match_id:
            return Decision("waiting", True, reason="not_connected")
        from .maps import map_ready
        if not map_ready(o.map_id):
            return Decision("waiting", True, reason="unsupported_map")
        if self.match_id != o.match_id:
            self.match_id = o.match_id
            self.epoch += 1
            self.round_key = None
            self.buy_attempted.clear()
            self.finished = False
            self.closed_rounds.clear()
        if o.phase == Phase.FINISHED:
            self.finished = True
        if self.finished:
            return Decision("finished", True, reason="match_finished")
        if not o.own_player:
            return Decision("spectating", True)
        if o.team not in ("T", "CT") or o.round_number < 0:
            return Decision("waiting", True, reason="unknown_side_or_round")
        key = (self.epoch, o.round_number, o.team)
        if self.round_key is not None and o.round_number < self.round_key[1]:
            return Decision("waiting", True, reason="round_regression")
        previous_key = self.round_key
        if previous_key is not None and previous_key[1] == o.round_number and previous_key[2] != o.team:
            return Decision("waiting", True, reason="side_changed_inside_round")
        self.round_key = key
        if o.phase == Phase.OVER or (o.phase == Phase.LIVE and not o.alive):
            self.closed_rounds.add(key)
        if key in self.closed_rounds:
            return Decision("round_inactive", True)
        if not o.alive:
            return Decision("dead", True)
        enemy = "CT" if o.team == "T" else "T"
        if o.phase == Phase.FREEZE:
            if o.buy_allowed and valid_money(o.money) and key not in self.buy_attempted:
                # Reserve before returning. The executor must confirm each purchase;
                # uncertain output must not lead to an automatic replay of the basket.
                self.buy_attempted.add(key)
                return Decision("buy", True, enemy_team=enemy,
                                buy_key=f"{self.epoch}:{o.round_number}:{o.team}")
            return Decision("freeze", True, enemy_team=enemy)
        if o.phase != Phase.LIVE:
            return Decision(o.phase.value, True, enemy_team=enemy)
        if o.bomb in ("defused", "exploded"):
            return Decision("round_resolving", True, enemy_team=enemy)
        objective = ({"planted": "defuse"}.get(o.bomb, "defend_site") if o.team == "CT"
                     else {"planted": "defend_bomb", "carried_self": "plant",
                           "dropped": "recover_bomb", "carried_other": "support_carrier", "not_carried_self": "support_site"}.get(o.bomb))
        if objective is None:
            return Decision("waiting", True, enemy_team=enemy, reason="unknown_bomb_state")
        return Decision("live", False, True, True, enemy, objective)


def valid_money(value):
    return type(value) is int and 0 <= value <= 16000
