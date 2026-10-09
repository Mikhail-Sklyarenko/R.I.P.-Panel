"""Classify CS2/Steam screens for the fleet agent. Absence of evidence is UNKNOWN.

Menu clicks are never authorised from a single colour probe. Critical states
need a named label (or GSI) plus a short consecutive streak.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from core.wingman_fleet.models import Screen
from modules.ui_nav.menu_labels import play_button, start_button_available, wingman_label_present

REQUIRED = (1280, 720)
STREAK_NEED = 2


@dataclass(frozen=True)
class ScreenEvidence:
    state: Screen
    confidence: float
    reason: str
    frame_id: int = 0
    evidence: tuple[str, ...] = ()
    blocking_modal: str = ""
    size: tuple[int, int] = (0, 0)
    observed_at: float = 0.0


def _pixels(image: Image.Image) -> list[int]:
    getter = getattr(image, "get_flattened_data", None)
    if callable(getter):
        return list(getter())
    return list(image.getdata())


def _ink_ratio(image: Image.Image, box: tuple[int, int, int, int], threshold: int = 160) -> float:
    crop = image.convert("L").crop(box)
    pixels = _pixels(crop)
    if not pixels:
        return 0.0
    return sum(1 for p in pixels if p >= threshold) / len(pixels)


def _probe(image: Image.Image, spec: dict[str, Any]) -> bool:
    x, y = int(spec["x"]), int(spec["y"])
    if x >= image.width or y >= image.height:
        return False
    px = image.getpixel((x, y))[:3]
    tr, tg, tb = spec["rgb"]
    tol = int(spec.get("tolerance", 40))
    return abs(px[0] - tr) <= tol and abs(px[1] - tg) <= tol and abs(px[2] - tb) <= tol


def load_spec(root: Path | None = None) -> dict[str, Any]:
    from config.paths import get_app_root
    path = (root or get_app_root()) / "resources" / "ui_nav" / "wingman_fleet.yaml"
    if not path.is_file():
        return {}
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


class MenuObserver:
    """Stateful classifier: GSI first, then labels, then calibrated probes."""

    def __init__(self, spec: dict[str, Any] | None = None):
        self.spec = spec if spec is not None else load_spec()
        self._last = Screen.UNKNOWN
        self._streak = 0
        self._frame = 0
        self.calibrated = bool(self.spec.get("clicks"))

    def classify(self, image: Image.Image | None, *, gsi_mode: str = "", gsi_map: str = "",
                 gsi_phase: str = "", gsi_fresh: bool = False, steam_running: bool = False,
                 cs2_running: bool = False) -> ScreenEvidence:
        self._frame += 1
        if not steam_running:
            return self._commit(Screen.NO_STEAM, 1.0, "steam_process_missing")
        if not cs2_running:
            return self._commit(Screen.STEAM_ONLY, 1.0, "cs2_process_missing")
        if gsi_fresh and gsi_phase == "gameover":
            return self._commit(Screen.MATCH_RESULT, 0.95, "gsi_gameover", ("gsi",))
        if gsi_fresh and gsi_mode == "scrimcomp2v2" and gsi_map == "de_inferno":
            if gsi_phase in ("live", "warmup", "intermission"):
                return self._commit(Screen.IN_MATCH, 0.95, "gsi_in_match", ("gsi", gsi_phase))
        if image is None:
            return self._commit(Screen.UNKNOWN, 0.0, "no_frame")
        if image.size != REQUIRED:
            return self._commit(Screen.UNKNOWN, 0.0, "uncalibrated_resolution",
                                (f"{image.width}x{image.height}",))
        labels = self.spec.get("labels") or {}
        probes = self.spec.get("probes") or {}
        hits: list[str] = []
        if _play_hit(image) or _label(image, labels.get("play")):
            hits.append("play")
        if _label(image, labels.get("wingman")) or wingman_label_present(image, "wingman"):
            hits.append("wingman")
        if _label(image, labels.get("inferno")) or wingman_label_present(image, "inferno"):
            hits.append("inferno")
        if (_label(image, labels.get("searching")) or _any_probe(image, probes.get("searching"))
                or wingman_label_present(image, "searching")):
            hits.append("searching")
        if _label(image, labels.get("confirm")) or wingman_label_present(image, "confirm"):
            hits.append("confirm")
        if _label(image, labels.get("invite")) or wingman_label_present(image, "invite"):
            hits.append("invite")
        modal = ""
        if _any_probe(image, probes.get("modal")) and "play" not in hits and "wingman" not in hits:
            modal = "blocking_dialog"
        if "confirm" in hits:
            return self._commit(Screen.MATCH_CONFIRM, 0.9, "confirm_banner", tuple(hits))
        if "searching" in hits:
            return self._commit(Screen.SEARCHING, 0.85, "searching_ui", tuple(hits))
        if "invite" in hits and "play" not in hits:
            return self._commit(Screen.PLAY_MENU, 0.8, "invite_dialog", tuple(hits), blocking_modal="invite")
        if "play" in hits and ("wingman" in hits or start_button_available(image)):
            return self._commit(Screen.PLAY_MENU, 0.86, "play_page", tuple(hits))
        if "play" in hits:
            return self._commit(Screen.MAIN_MENU, 0.86, "main_menu_bar", tuple(hits))
        if modal:
            return self._commit(Screen.MODAL, 0.6, "modal_probe", (modal,), blocking_modal=modal)
        if gsi_fresh and gsi_map:
            return self._commit(Screen.LOADING, 0.55, "gsi_map_without_hud", ("gsi",))
        return self._commit(Screen.UNKNOWN, 0.0, "no_verified_overlay", tuple(hits),
                            blocking_modal=modal)

    def _commit(self, state: Screen, conf: float, reason: str, evidence: tuple[str, ...] = (),
                blocking_modal: str = "") -> ScreenEvidence:
        if state is self._last:
            self._streak += 1
        else:
            self._last, self._streak = state, 1
        now = time.monotonic()
        if state not in (Screen.UNKNOWN, Screen.NO_STEAM, Screen.STEAM_ONLY) and self._streak < STREAK_NEED:
            return ScreenEvidence(Screen.UNKNOWN, conf, "awaiting_streak", self._frame, evidence,
                                  blocking_modal, REQUIRED, now)
        return ScreenEvidence(state, conf, reason, self._frame, evidence, blocking_modal, REQUIRED, now)

    def click_point(self, name: str) -> tuple[int, int] | None:
        clicks = self.spec.get("clicks") or {}
        pt = clicks.get(name)
        if not isinstance(pt, dict):
            return None
        return int(pt["x"]), int(pt["y"])


def _play_hit(image: Image.Image) -> bool:
    try:
        return play_button(image) is not None
    except Exception:
        return False


def _label(image: Image.Image, spec: dict[str, Any] | None) -> bool:
    if not spec or "box" not in spec:
        return False
    box = tuple(int(v) for v in spec["box"])
    return _ink_ratio(image, box) >= 0.08


def _any_probe(image: Image.Image, probes: list | None) -> bool:
    return bool(probes) and any(_probe(image, p) for p in probes if isinstance(p, dict))
