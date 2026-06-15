"""Detect DM map from match-ready popup or scoreboard header."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np
from PIL import Image

from map.ocr import ocr_map_crop
from map.parse import MapScriptId, parse_map_script
from map.regions import MapRegionSet, OcrRect
from map.template_match import MapTemplate, crop_gray, match_map_templates
from team.hud_team_detect import score_probes

DetectSource = Literal["match_ready", "scoreboard"]


def _fit_frame(img: np.ndarray, base_w: int, base_h: int) -> np.ndarray:
    h, w = img.shape[:2]
    if w == base_w and h == base_h:
        return img
    pil = Image.fromarray(img)
    resized = pil.resize((base_w, base_h), Image.Resampling.LANCZOS)
    return np.asarray(resized)


def _crop_rgb(img: np.ndarray, rect: OcrRect) -> np.ndarray:
    return img[rect.y : rect.y + rect.h, rect.x : rect.x + rect.w]


def _crop_pil(img: np.ndarray, rect: OcrRect) -> Image.Image:
    crop = _crop_rgb(img, rect)
    return Image.fromarray(crop)


def match_ready_visible(img: np.ndarray, regions: MapRegionSet) -> bool:
    votes = score_probes(img, regions.match_ready_probes)
    return votes >= regions.match_ready_min_votes


def detect_map_hud(
    img: np.ndarray,
    regions: MapRegionSet,
    templates: tuple[MapTemplate, ...],
    *,
    use_ocr_fallback: bool = True,
) -> tuple[Optional[MapScriptId], Optional[DetectSource]]:
    """
    Return (map_script, source) when dust2/mirage is recognized; (None, None) otherwise.
    """
    frame = _fit_frame(img, regions.base_width, regions.base_height)
    threshold = regions.template_threshold

    if match_ready_visible(frame, regions):
        crop = _crop_rgb(frame, regions.match_ready_ocr)
        matched = match_map_templates(
            crop,
            templates,
            source="match_ready",
            threshold=threshold,
        )
        if matched is not None:
            return matched, "match_ready"
        if use_ocr_fallback:
            text = ocr_map_crop(_crop_pil(frame, regions.match_ready_ocr))
            parsed = parse_map_script(text)
            if parsed is not None:
                return parsed, "match_ready"

    crop = _crop_rgb(frame, regions.scoreboard_ocr)
    matched = match_map_templates(
        crop,
        templates,
        source="scoreboard",
        threshold=threshold,
    )
    if matched is not None:
        return matched, "scoreboard"

    if use_ocr_fallback:
        text = ocr_map_crop(_crop_pil(frame, regions.scoreboard_ocr))
        parsed = parse_map_script(text)
        if parsed is not None:
            return parsed, "scoreboard"

    return None, None


@dataclass
class MapDetectState:
    pending_script: Optional[str] = None
    pending_count: int = 0
    confirmed_script: str = "generic_dm"
    locked: bool = False

    @classmethod
    def from_script(cls, script: str) -> MapDetectState:
        name = script.strip().lower() or "generic_dm"
        if name not in ("dust2", "mirage", "generic_dm"):
            name = "generic_dm"
        return cls(confirmed_script=name)


def update_map_hysteresis(
    state: MapDetectState,
    winner: Optional[MapScriptId],
    *,
    confirm_frames: int,
    lock_after_confirm: bool,
) -> tuple[Optional[MapScriptId], int]:
    """
    Apply hysteresis. Returns (new_confirmed_script_if_changed, pending_count).
    """
    if state.locked:
        return None, 0

    if winner is None:
        state.pending_script = None
        state.pending_count = 0
        return None, 0

    if winner == state.pending_script:
        state.pending_count += 1
    else:
        state.pending_script = winner
        state.pending_count = 1

    if (
        state.pending_count >= confirm_frames
        and winner != state.confirmed_script
    ):
        state.confirmed_script = winner
        state.pending_script = None
        state.pending_count = 0
        if lock_after_confirm:
            state.locked = True
        return winner, confirm_frames

    return None, state.pending_count
