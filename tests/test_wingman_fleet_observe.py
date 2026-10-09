"""Menu observer, match fingerprint parser and fail-closed live command path."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from core.wingman_fleet.models import Command, CommandType, ResultStatus, Screen
from modules.fleet_agent.match_status import fingerprint_from_names, parse_status
from modules.fleet_agent.observe import MenuObserver, STREAK_NEED, load_spec
from modules.ui_nav.coords import load_nav_coords
from modules.ui_nav.detectors import WingmanMenuState, detect_wingman_menu
from modules.ui_nav.menu_labels import wingman_label_present

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "wingman_fleet"


def _frame(hits=()):
    im = Image.new("RGB", (1280, 720), (18, 20, 24))
    draw = ImageDraw.Draw(im)
    font = ImageFont.load_default()
    if "play" in hits:
        draw.rectangle((633, 12, 685, 30), fill=(240, 240, 240))
        draw.rectangle((529, 12, 604, 30), fill=(230, 230, 230))
        draw.rectangle((789, 12, 841, 30), fill=(230, 230, 230))
        draw.text((640, 14), "PLAY", fill=(10, 10, 10), font=font)
    if "wingman" in hits:
        draw.rectangle((720, 78, 820, 102), fill=(250, 250, 250))
    if "searching" in hits:
        draw.rectangle((560, 240, 720, 290), fill=(220, 220, 220))
        draw.rectangle((630, 350, 650, 370), fill=(200, 200, 200))
    if "confirm" in hits:
        draw.rectangle((500, 330, 780, 380), fill=(255, 255, 255))
    return im


def _spec():
    return {
        "clicks": {"start_search": {"x": 1125, "y": 691}, "play": {"x": 663, "y": 20}},
        "labels": {
            "play": {"box": [633, 12, 685, 30]},
            "wingman": {"box": [720, 78, 820, 102]},
            "searching": {"box": [560, 240, 720, 290]},
            "confirm": {"box": [500, 330, 780, 380]},
        },
        "probes": {"searching": [{"x": 640, "y": 360, "rgb": [200, 200, 200], "tolerance": 20}]},
    }


def test_unknown_until_streak_and_gsi_outranks_pixels():
    obs = MenuObserver(_spec())
    ev = obs.classify(_frame(("play",)), steam_running=True, cs2_running=True)
    assert ev.state is Screen.UNKNOWN and ev.reason == "awaiting_streak"
    for _ in range(STREAK_NEED - 1):
        ev = obs.classify(_frame(("play",)), steam_running=True, cs2_running=True)
    # play_button needs loadout/news templates from disk; without them stay unknown or main
    gsi = obs.classify(None, gsi_mode="scrimcomp2v2", gsi_map="de_inferno", gsi_phase="live",
                       gsi_fresh=True, steam_running=True, cs2_running=True)
    gsi2 = obs.classify(None, gsi_mode="scrimcomp2v2", gsi_map="de_inferno", gsi_phase="live",
                        gsi_fresh=True, steam_running=True, cs2_running=True)
    assert gsi2.state is Screen.IN_MATCH
    over = obs.classify(None, gsi_mode="scrimcomp2v2", gsi_map="de_inferno", gsi_phase="gameover",
                        gsi_fresh=True, steam_running=True, cs2_running=True)
    over2 = obs.classify(None, gsi_mode="scrimcomp2v2", gsi_map="de_inferno", gsi_phase="gameover",
                         gsi_fresh=True, steam_running=True, cs2_running=True)
    assert over2.state is Screen.MATCH_RESULT
    assert obs.classify(None, steam_running=False, cs2_running=False).state is Screen.NO_STEAM


def test_search_and_confirm_need_named_evidence():
    obs = MenuObserver(_spec())
    for _ in range(STREAK_NEED):
        ev = obs.classify(_frame(("searching",)), steam_running=True, cs2_running=True)
    assert ev.state is Screen.SEARCHING
    obs = MenuObserver(_spec())
    for _ in range(STREAK_NEED):
        ev = obs.classify(_frame(("confirm",)), steam_running=True, cs2_running=True)
    assert ev.state is Screen.MATCH_CONFIRM
    wrong = MenuObserver(_spec()).classify(Image.new("RGB", (1920, 1080)), steam_running=True, cs2_running=True)
    assert wrong.reason == "uncalibrated_resolution"


def test_status_parser_ignores_score_and_uses_server_plus_names():
    text = """
hostname: Valve CS2 Server
udp/ip  : 162.1.2.3:27015
# userid name uniqueid
# 2 1 "Alpha" [U:1:1]
# 3 2 "Bravo" [U:1:2]
# 4 3 "Charlie" [U:1:3]
# 5 4 "Delta" [U:1:4]
"""
    fp = parse_status(text)
    assert fp is not None
    assert fp.server_token.startswith("162.1.2.3")
    assert set(fp.players) == {"Alpha", "Bravo", "Charlie", "Delta"}
    assert parse_status("") is None
    names = fingerprint_from_names("s1", ("Alpha", "Bravo", "Charlie", "Delta"))
    assert names.server_token == "s1"


def test_recorded_fixtures_and_yaml_spec():
    assert load_spec().get("clicks", {}).get("start_search")
    searching = Image.open(FIXTURE_DIR / "searching.png")
    confirm = Image.open(FIXTURE_DIR / "confirm.png")
    play = Image.open(FIXTURE_DIR / "main_menu.png")
    assert wingman_label_present(searching, "searching")
    obs = MenuObserver(_spec())
    for _ in range(STREAK_NEED):
        ev = obs.classify(searching, steam_running=True, cs2_running=True)
    assert ev.state is Screen.SEARCHING and ev.observed_at > 0
    obs = MenuObserver(_spec())
    for _ in range(STREAK_NEED):
        ev = obs.classify(confirm, steam_running=True, cs2_running=True)
    assert ev.state is Screen.MATCH_CONFIRM
    obs = MenuObserver(_spec())
    for _ in range(STREAK_NEED):
        ev = obs.classify(play, steam_running=True, cs2_running=True)
    assert ev.state is Screen.MAIN_MENU
    coords = load_nav_coords("1280x720")
    assert detect_wingman_menu(searching, coords) is WingmanMenuState.SEARCHING
    assert detect_wingman_menu(confirm, coords) is WingmanMenuState.MATCH_CONFIRM


def test_live_backend_refuses_gameplay_without_lease(monkeypatch, tmp_path):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    from config.loader import ensure_config
    ensure_config()
    from modules.fleet_agent.backend import ExecContext
    from modules.fleet_agent.live import WindowsBackend
    import threading
    be = WindowsBackend(agent_id="pc1", capture=lambda: Image.new("RGB", (1280, 720)))
    cmd = Command("x", "run", "pc1", CommandType.START_GAMEPLAY, {"attempt_id": "w1"})
    ctx = ExecContext(threading.Event(), lambda: 0.0, lambda: "")
    res = be.execute(cmd, ctx)
    assert res.status is ResultStatus.REJECTED and res.reason == "gameplay_not_admitted"
    be.close()
