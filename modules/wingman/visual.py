"""Calibrated HUD evidence. Absence of an overlay never means a live round."""
from dataclasses import dataclass
from pathlib import Path
import json
from PIL import Image, ImageChops
from .engine import Decision


@dataclass(frozen=True)
class VisualEvidence:
    state: str
    confidence: float
    reason: str
    observed_at: float


def ink(image, threshold):
    red, green, blue = image.convert("RGB").split()
    value = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    return value.point(lambda x: 255 if x >= threshold else 0, mode="1")


def count(image):
    return image.histogram()[-1]


class HudReader:
    def __init__(self, root=None):
        if root is None:
            from config.paths import get_app_root
            root = get_app_root() / "resources/wingman/hud_ru_1280"
        self.root = Path(root)
        self.spec = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        self.templates = {}
        for entry in self.spec["templates"]:
            with Image.open(self.root / (entry["name"] + ".png")) as im:
                self.templates[entry["name"]] = im.convert("RGB").copy()

    def score(self, image, entry):
        x1,y1,x2,y2 = entry["box"]
        template = self.templates[entry["name"]]
        best = 0.0
        # Separate text from the translucent UI background; tolerate 2 px drift.
        for threshold in (140, 185, 215):
            target = ink(template, threshold)
            n = count(target)
            if n < 12:
                continue
            region = ink(image.crop((x1-2,y1-2,x2+2,y2+2)), threshold)
            for dy in range(5):
                for dx in range(5):
                    crop = region.crop((dx,dy,dx+x2-x1,dy+y2-y1))
                    both = count(ImageChops.logical_and(target,crop))
                    best = max(best, 2*both/max(1,n+count(crop)))
        return best

    def read(self, image, *, now):
        if image.size != tuple(self.spec["resolution"]):
            return VisualEvidence("unknown", 0., "uncalibrated_resolution", now)
        scores = {e["name"]:self.score(image,e) for e in self.spec["templates"]}
        # Terminal overlays outrank held weapons, live-looking HUD and prompts.
        candidates = [("finished", min(scores["match_result"],scores["match_victory"])),
                      ("halftime", scores["halftime"]),
                      ("round_over", max(scores["round_win"],scores["round_loss"])),
                      ("buy_menu", min(scores["buy_header"],scores["buy_rifles"])),
                      ("defusing", scores["defuse"])]
        for state, score in candidates:
            if score >= .86:
                return VisualEvidence(state, score, "recognized_hud_text", now)
        return VisualEvidence("unknown", max(scores.values()), "no_verified_overlay", now)


def guard_decision(decision: Decision, evidence: VisualEvidence, *, now: float) -> Decision:
    """A visual veto, not a replacement for round/player observations.

    In particular, a live-looking image cannot authorize combat by itself.
    """
    if not 0 <= now-evidence.observed_at <= .5:
        return Decision("waiting", True, reason="stale_visual_frame")
    if evidence.reason == "uncalibrated_resolution":
        return Decision("waiting", True, reason=evidence.reason)
    if evidence.state in ("finished", "halftime", "round_over", "buy_menu", "defusing"):
        return Decision(evidence.state, True, reason="visual_"+evidence.state,
                        preserve_interaction=(evidence.state == "defusing" and
                                              decision.objective == "defuse" and decision.state == "live"))
    return decision
