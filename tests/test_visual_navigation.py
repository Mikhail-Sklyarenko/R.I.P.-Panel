"""Navigation acceptance tests with a simulated world, not desired poses as truth."""
from __future__ import annotations

import importlib
import math
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture(autouse=True, scope="module")
def imports(csgobot_module_path):
    global Pose, Controller, Walkable, Localizer
    Pose = importlib.import_module("nav.pose").PoseResult
    Controller = importlib.import_module("nav.visual_controller").VisualNavController
    Walkable = importlib.import_module("nav.walkable").WalkableMap
    Localizer = importlib.import_module("nav.visual_localizer").VisualLocalizer


def pack(goal=(.8, .2)):
    g = SimpleNamespace(id="finish", x=goal[0], y=goal[1], arrive_radius=.015)
    return SimpleNamespace(map_id="test", goal=g, goals=(g,), strategy="single",
        route=SimpleNamespace(dwell_at_goal_sec=1.),
        humanize=SimpleNamespace(turn_rate_deg_per_sec=110.))


def make_controller(mask, goal=(.8, .2)):
    keys, mouse = set(), []
    c = Controller(pack(goal), SimpleNamespace(fov=SimpleNamespace(x360=3600)),
        keys.add, keys.discard, lambda x, y: mouse.append(x / 10.),
        walkable=Walkable(mask, clearance_px=3, grid_step=2))
    return c, keys, mouse


def pose(x, y, yaw, now):
    return Pose(x, y, yaw, .9, True, 20, "visual", None, now)


def test_key_lease_expires_without_controller_ticks():
    from nav.input_lease import KeyLease
    clock = [1.]
    held = set()
    lease = KeyLease(held.add, held.discard, clock=lambda: clock[0])
    lease.renew(.25)
    lease.set_keys({"w", "shift"})
    assert held == {"w", "shift"}
    clock[0] = 1.26
    lease.expire()
    assert not held
    lease.set_keys({"w"})
    assert not held
    lease.close()


def test_shipped_mvp_has_connected_goals_and_blocks_other_spawns():
    from nav.pack import load_nav_pack
    from nav.paths import resolve_nav_pack_path
    from nav.pack_resolve import measured_runtime_pack
    route = load_nav_pack(resolve_nav_pack_path("dust2_visual_mvp"))
    ground = Walkable.load(route.map_id)
    a, b = [(g.x, g.y) for g in route.goals]
    assert ground.plan(a, b) and ground.plan(b, a)
    assert not ground.contains((.225, .824))  # Measured T spawn is outside MVP.
    assert measured_runtime_pack("dust2_dm", "auto") == "dust2_visual_mvp"
    assert measured_runtime_pack("dust2_dm", "dust2_dm") == "dust2_dm"


def test_small_pose_noise_cannot_hide_a_wall_stop():
    c, keys, _ = make_controller(np.full((200, 200), 255, np.uint8))
    stuck = False
    for i in range(120):
        t = 1 + i * .05
        result = c.tick(pose(.2 + .006 * math.sin(i), .2, 0, t), now=t, paused=False)
        stuck |= result.stuck_event
    assert stuck and not keys and c.state.value == "blocked"


def test_never_treat_desired_direction_or_place_as_heading():
    c, keys, mouse = make_controller(np.full((200, 200), 255, np.uint8))
    c.tick(pose(.2, .2, 180, 1), now=1, paused=False)
    assert "w" not in keys
    for i in range(1, 60):
        t = 1 + i * .05
        # Mouse can be ignored by the game: the observed heading never changes.
        c.tick(pose(.2, .2, 180, t), now=t, paused=False)
    assert mouse and "w" not in keys
    c.tick(Pose(.2, .2, 0, .99, True, 20, "world", "spawn"), now=5, paused=False)
    assert not keys


def test_stale_or_missing_pose_releases_all_keys():
    c, keys, _ = make_controller(np.full((200, 200), 255, np.uint8))
    p = pose(.2, .2, 0, 1)
    assert c.tick(p, now=1, paused=False).forward_held
    c.tick(p, now=1.3, paused=False)
    assert not keys and c.state.value == "wait_pose"
    c.tick(pose(.2, .2, 0, 2), now=2, paused=False)
    c.tick(Pose.invalid(), now=2.1, paused=False)
    assert not keys


def test_wall_stop_cannot_be_rearmed_by_ticks_or_fake_flow():
    c, keys, _ = make_controller(np.full((200, 200), 255, np.uint8))
    stopped = False
    for i in range(120):
        t = 1 + i * .05
        r = c.tick(pose(.2, .2, 0, t), now=t, paused=False, radar_progressing=True)
        stopped |= r.stuck_event
        if t > 2.3:
            assert not keys
    assert stopped and c.state.value == "blocked"


def test_disconnected_and_corner_cutting_routes_are_rejected():
    mask = np.full((100, 100), 255, np.uint8)
    mask[:, 48:52] = 0
    m = Walkable(mask, clearance_px=2, grid_step=2)
    assert not m.plan((.2, .5), (.8, .5))
    assert not m.plan((.49, .5), (.8, .5))
    assert not m.visible((.2, .5), (.8, .5))
    assert not m.contains((1., 1.))


@pytest.mark.parametrize("initial_yaw", [0, 90, 180, -90])
def test_simulated_l_corridor_reaches_goal_without_collisions(initial_yaw):
    mask = np.zeros((240, 240), np.uint8)
    mask[150:220, 20:220] = 255
    mask[20:220, 150:220] = 255
    c, keys, mouse = make_controller(mask, goal=(.78, .18))
    x, y, yaw = .2, .78, initial_yaw
    collisions = 0
    for i in range(2000):
        t, dt = 1 + i * .05, .05
        # Simulate a turn by another subsystem midway through a walk.
        if i == 110:
            yaw += 65
        r = c.tick(pose(x, y, yaw, t), now=t, paused=False)
        yaw += sum(mouse)
        mouse.clear()
        speed = 24 if "shift" in keys else 48
        direction = (1 if "w" in keys else 0) - (1 if "s" in keys else 0)
        nx = x + direction * math.cos(math.radians(yaw)) * speed * dt / 239
        ny = y + direction * math.sin(math.radians(yaw)) * speed * dt / 239
        if not c.walkable.visible((x, y), (nx, ny)):
            collisions += 1
        else:
            x, y = nx, ny
        if r.state.value == "at_goal":
            break
    assert r.state.value == "at_goal", (r.reason, x, y, yaw)
    assert collisions == 0
    assert math.hypot(x - .78, y - .18) < .03


def texture():
    import cv2
    rng = np.random.default_rng(42)
    rgb = np.full((500, 500, 3), 35, np.uint8)
    for _ in range(170):
        x, y = rng.integers(15, 470, size=2)
        color = tuple(int(v) for v in rng.integers(60, 240, size=3))
        cv2.rectangle(rgb, (int(x), int(y)), (int(x + rng.integers(5, 20)), int(y + rng.integers(5, 20))), color, -1)
    return rgb


def test_registration_recovers_rotation_translation_scale_and_yaw(tmp_path):
    import cv2
    rgb = texture()
    loc = Localizer("test", map_rgb=rgb, profile_dir=tmp_path)
    world_to_crop = cv2.getRotationMatrix2D((250., 250.), 32., .8)
    world_to_crop[:, 2] -= 140
    crop = cv2.warpAffine(rgb, world_to_crop, (220, 220))
    mask = np.zeros((220, 220), np.uint8)
    cv2.circle(mask, (110, 110), 103, 255, -1)
    cv2.circle(mask, (110, 110), 18, 0, -1)
    inverse = cv2.invertAffineTransform(world_to_crop)
    expected = inverse @ np.array([110., 110., 1.])
    icon = Pose(.5, .5, -90., .95, True, 30, "centered")
    assert not loc.locate(crop, mask, (110, 110), icon, now=1.).valid
    p = loc.locate(crop, mask, (110, 110), icon, now=1.1)
    assert p.valid, loc.reason
    assert np.linalg.norm(np.array([p.x_norm, p.y_norm]) * 499 - expected) < 3
    vector = inverse[:, :2] @ np.array([0., -1.])
    assert abs(p.yaw_deg - math.degrees(math.atan2(vector[1], vector[0]))) < 2
    assert p.observed_at == 1.1


def test_registration_rejects_blank_and_unrelated_frames(tmp_path):
    loc = Localizer("test", map_rgb=texture(), profile_dir=tmp_path)
    mask = np.full((220, 220), 255, np.uint8)
    assert loc.register(np.zeros((220, 220, 3), np.uint8), mask) is None
    noise = np.random.default_rng(23).integers(0, 255, size=(220, 220, 3), dtype=np.uint8)
    assert loc.register(noise, mask) is None


def test_visual_filter_never_holds_last_pose():
    module = importlib.import_module("nav.pose_filter")
    cfg = importlib.import_module("nav.calibration").PoseFilterConfig(.35, .8, .35)
    f = module.PoseFilter(cfg)
    p = pose(.2, .2, 20, 1)
    assert f.update(p, now=1) is p
    assert not f.update(Pose.invalid(), now=1.05).valid


@pytest.mark.parametrize("yaw", [0, 90, 180, -90])
def test_heading_uses_white_tip_not_round_colored_body(yaw):
    import cv2
    observe = importlib.import_module("nav.icon_heading").observe_heading
    rgb = np.full((40, 40, 3), 60, np.uint8)
    body = np.zeros((40, 40), np.uint8)
    cv2.circle(body, (20, 20), 5, 1, -1)
    rgb[body > 0] = (250, 220, 40)
    tx = round(20 + 7 * math.cos(math.radians(yaw)))
    ty = round(20 + 7 * math.sin(math.radians(yaw)))
    cv2.circle(rgb, (tx, ty), 1, (250, 250, 240), -1)
    measured, confidence = observe(rgb, body > 0)
    error = (measured - yaw + 180) % 360 - 180
    assert abs(error) < 5 and confidence > .8
    rgb[~(body > 0)] = 60
    assert observe(rgb, body > 0) is None


def test_real_hud_heading_has_downward_white_tip():
    import cv2
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    frame = cv2.cvtColor(cv2.imread(str(root / "resources/nav/maps/de_dust2/hud_ref/mid_frame.jpg")), cv2.COLOR_BGR2RGB)
    paths = importlib.import_module("nav.paths")
    cal = importlib.import_module("nav.calibration").load_calibration(paths.resolve_calibration_path())
    reader = importlib.import_module("nav.minimap_reader").MinimapReader(cal)
    reader.read(frame)
    crop, *_ = reader._crop_from_circle(frame, reader.last_circle)
    measured, confidence = importlib.import_module("nav.icon_heading").observe_heading(crop, reader.last_icon_component)
    # Independently inspected pale tip points down in the supplied image.
    assert abs(measured - 90) < 12 and confidence > .8


def test_blocked_path_recovers_only_along_observed_ground():
    mask = np.full((200, 200), 255, np.uint8)
    c, keys, mouse = make_controller(mask, goal=(.8, .5))
    x, y, yaw = .2, .5, 0.
    recovered = False
    for i in range(600):
        t = 1 + i * .05
        r = c.tick(pose(x, y, yaw, t), now=t, paused=False)
        yaw += sum(mouse); mouse.clear()
        recovered |= "s" in keys
        direction = int("w" in keys) - int("s" in keys)
        nx = x + direction * math.cos(math.radians(yaw)) * .008
        # Unmapped obstacle in the simulated world at x=.5.
        if nx < .5:
            x = nx
        if r.state.value == "blocked":
            break
    assert recovered
    assert r.state.value == "blocked" and not keys


def test_pause_releases_walk_modifier_and_reacquires_heading():
    c, keys, mouse = make_controller(np.full((200, 200), 255, np.uint8))
    c.tick(pose(.7, .2, 0, 1), now=1, paused=False)
    assert keys == {"w", "shift"}
    c.tick(pose(.7, .2, 0, 1.1), now=1.1, paused=True)
    assert not keys
    c.tick(pose(.7, .2, 180, 1.2), now=1.2, paused=False)
    assert not keys


def test_calibrated_hud_atlas_works_without_matching_base_map(tmp_path):
    import cv2
    import json
    rgb = texture()[100:350, 100:350].copy()
    assert cv2.imwrite(str(tmp_path / "reference.png"), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    matrix = [[1., 0., 100.], [0., 1., 100.]]
    (tmp_path / "atlas.json").write_text(json.dumps({"map_id":"test", "references":[{"image":"reference.png", "to_map":matrix}]}))
    loc = Localizer("test", map_rgb=np.zeros((500, 500, 3), np.uint8), profile_dir=tmp_path)
    mask = np.full(rgb.shape[:2], 255, np.uint8)
    r = loc.register(rgb, mask)
    assert r is not None and r.source == "reference.png"
    assert np.allclose(r.matrix, matrix, atol=.2)


def test_replay_command_writes_frame_diagnostics_without_game_input(tmp_path):
    import cv2
    import subprocess
    import sys
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    frame = cv2.imread(str(root / "resources/nav/maps/de_dust2/hud_ref/mid_frame.jpg"))
    video, output = tmp_path / "input.avi", tmp_path / "replay.jsonl"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10., (1280, 720))
    assert writer.isOpened()
    for _ in range(3):
        writer.write(frame)
    writer.release()
    result = subprocess.run([sys.executable, str(root / "scripts/nav_workbench.py"),
        "replay", "--video", str(video), "--output", str(output)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 3 and all("reason" in row and "observed_at" in row for row in rows)
    assert json.loads(result.stdout)["frames"] == 3
