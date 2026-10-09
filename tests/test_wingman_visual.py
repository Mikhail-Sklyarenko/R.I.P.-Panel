from pathlib import Path
import json
from dataclasses import replace
import pytest
from PIL import Image
from modules.wingman.visual import HudReader, VisualEvidence, guard_decision
from modules.wingman.engine import Decision, RoundEngine, Observation, Phase

ROOT = Path(__file__).parent / "fixtures/wingman/hud"
LABELS = json.loads((ROOT / "labels.json").read_text())["frames"]


@pytest.fixture(scope="module")
def reader():
    return HudReader()


@pytest.mark.parametrize("name,expected", list(LABELS.items()))
def test_held_out_video_frames(reader, name, expected):
    with Image.open(ROOT / name) as image:
        evidence = reader.read(image, now=10)
    assert evidence.state == expected


@pytest.mark.parametrize("size", [(1280,720),(640,360),(1920,1080)])
def test_blank_image_never_authorizes_live(reader, size):
    assert reader.read(Image.new("RGB", size), now=10).state == "unknown"


def test_visual_unknown_cannot_enable_waiting_decision():
    decision = guard_decision(Decision("waiting", True),
        VisualEvidence("unknown", .4, "no_verified_overlay", 10), now=10)
    assert not decision.combat and not decision.navigation


def test_stale_frame_blocks_previously_live_decision():
    decision = guard_decision(Decision("live", False, True, True),
        VisualEvidence("unknown", .4, "no_verified_overlay", 9), now=10)
    assert decision.release_inputs and not decision.combat


def test_defuse_disables_camera_and_fire_without_cancelling_confirmed_interaction():
    decision = guard_decision(Decision("live", False, True, True, "T", "defuse"),
        VisualEvidence("defusing", .99, "recognized_hud_text", 10), now=10)
    assert not decision.navigation and not decision.combat
    assert decision.preserve_interaction
    spectator = guard_decision(Decision("spectating", True),
        VisualEvidence("defusing", .99, "recognized_hud_text", 10), now=10)
    assert not spectator.preserve_interaction


def test_victory_banner_prevents_plant_and_latches_round():
    engine = RoundEngine()
    observation = Observation(1,10,"match",0,"de_inferno",Phase.LIVE,True,True,"T",800,False,"carried_self")
    evidence = VisualEvidence("round_over", .99, "recognized_hud_text", 10)
    assert not engine.update_with_visual(observation,evidence,now=10).combat
    observation = replace(observation,sequence=2,observed_at=10.1)
    evidence = VisualEvidence("unknown", .4, "no_verified_overlay", 10.1)
    assert not engine.update_with_visual(observation,evidence,now=10.1).combat
    observation = replace(observation,sequence=3,observed_at=10.2,round_number=1)
    assert engine.update_with_visual(observation,evidence,now=10.2).combat


def test_stale_visual_does_not_consume_purchase_attempt():
    engine = RoundEngine()
    observation = Observation(1,10,"match",0,"de_inferno",Phase.FREEZE,True,True,"T",800,True)
    engine.update_with_visual(observation,VisualEvidence("unknown",0,"no_verified_overlay",8),now=10)
    assert not engine.buy_attempted


def test_one_result_label_without_victory_banner_is_not_match_end(reader):
    image = Image.new("RGB",(1280,720))
    entry = next(e for e in reader.spec["templates"] if e["name"] == "match_result")
    image.paste(reader.templates["match_result"],tuple(entry["box"][:2]))
    assert reader.read(image,now=10).state != "finished"
