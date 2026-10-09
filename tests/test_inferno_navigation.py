"""Inferno integration, random-spawn routing, and map-switch isolation."""
import importlib
import json
import random
import pytest
import numpy as np


@pytest.fixture
def nav(csgobot_module_path):
    return importlib.import_module('nav.farm_runtime')


def test_inferno_auto_pack_and_preflight(nav):
    from nav.pack_resolve import measured_runtime_pack, nav_pack_for_script
    from nav.preflight import run_nav_preflight
    assert measured_runtime_pack(nav_pack_for_script('inferno'), 'auto') == 'inferno_visual'
    result = run_nav_preflight(pack_id='auto')
    assert result['ok'], result['errors']
    assert 'inferno_visual' in result['packs_ok']
    from map.parse import parse_map_script
    for text in ('Deathmatch | Inferno', 'de_inferno', 'INFERNO'):
        assert parse_map_script(text) == 'inferno'
    assert parse_map_script('UnsupportedMap') is None


def test_inferno_confirmation_and_three_map_switch(nav):
    from nav.map_confirmation import active_map_confirmed, named_match_ready
    from nav.map_selector import VisualMapSelector
    from map.hud_map_detect import MapDetectState, update_map_hysteresis
    state = MapDetectState.from_script('dust2')
    for script in ('inferno', 'mirage', 'dust2', 'inferno'):
        for _ in range(3):
            update_map_hysteresis(state, script, confirm_frames=3, lock_after_confirm=True)
        assert active_map_confirmed('de_' + script, state)
        assert named_match_ready(script, 'match_ready')
        assert not named_match_ready(script, 'scoreboard')
    selector = VisualMapSelector.__new__(VisualMapSelector)
    selector.pending, selector.count = None, 0
    for _ in range(3):
        assert selector.confirm({'de_inferno': .85, 'de_dust2': .81}) is None
    assert selector.confirm({'de_inferno': .9, 'de_mirage': .3}) is None
    assert selector.confirm({'de_inferno': .9, 'de_mirage': .3}) is None
    assert selector.confirm({'de_inferno': .9, 'de_mirage': .3}) == 'de_inferno'


def test_inferno_floor_connects_major_areas_without_cutting_walls(nav):
    ground = nav.load_ground('de_inferno')
    assert ground is not None and ground.step == 2
    points = [(100,680),(450,530),(490,240),(900,350),(730,565),
              (810,700),(600,825),(430,770),(345,740)]
    for point in points:
        origin = ground.norm(point)
        assert ground.contains(origin), point
        path = ground.plan(origin, ground.norm((580,665)))
        assert path, point
        assert all(ground.visible(a,b) for a,b in zip(path,path[1:]))
    for blocked in ((20,20),(700,490),(660,300),(710,300)):
        assert not ground.contains(ground.norm(blocked))


def test_inferno_scattered_spawn_roaming(nav):
    from nav.roaming import RoamingGoals
    ground = nav.load_ground('de_inferno')
    roaming = RoamingGoals(ground, seed=29)
    ys, xs = np.nonzero(ground.grid)
    successes = 0
    for i in random.Random(29).sample(range(len(xs)), 30):
        origin = ground.norm((int(xs[i])*ground.step,int(ys[i])*ground.step))
        result = roaming.choose(origin)
        if result is None:
            continue
        goal, path = result
        assert all(ground.visible(a,b) for a,b in zip(path,path[1:]))
        successes += 1
    assert successes >= 28


def test_inferno_reloads_without_previous_map_pose(nav):
    from nav.pack import load_nav_pack
    from nav.paths import resolve_nav_pack_path
    from types import SimpleNamespace
    owner = nav.CameraOwnership(lambda *args: None, lambda: True)
    controller = nav.create_navigation(load_nav_pack(resolve_nav_pack_path('dust2_visual_mvp')),
        SimpleNamespace(x360=7792), lambda key:None, lambda key:None, owner,
        expanded=True, watchdog=False)
    for name in ('inferno_visual','mirage_visual','dust2_visual_mvp','inferno_visual'):
        controller.reload_pack(load_nav_pack(resolve_nav_pack_path(name)))
        assert controller.last_pose is None
        assert controller.walkable is not None
        assert controller._roaming is not None
        assert not controller._obstacles


def test_inferno_atlas_has_distributed_calibration_and_explicit_limits(nav):
    from nav.paths import resolve_visual_profile_file
    p = resolve_visual_profile_file('de_inferno','atlas.json')
    atlas = json.loads(p.read_text())
    centers = []
    for ref in atlas['references']:
        assert (p.parent / ref['image']).is_file()
        matrix = np.array(ref['to_map'])
        assert matrix.shape == (2,3) and np.isfinite(matrix).all()
        centers.append(matrix @ [112,112,1])
    assert np.ptp(centers,axis=0).min() > 650
    assert atlas['live_validated'] is False


def test_range_ring_removal_only_discards_hud_evidence(nav):
    from nav.hud_mask import exclude_range_ring
    original = np.zeros((240,240), np.uint8)
    original[20:220,20:220] = 255
    masked = exclude_range_ring(original.copy(),120,120,110)
    assert not np.any(masked > original)
    assert masked[120,200] == 0
    assert masked[120,150] == 255
    assert masked[120,120] == 255


def test_inferno_mask_rebuild_matches_shipped_asset(nav):
    import cv2
    import importlib.util
    from pathlib import Path
    from nav.paths import resolve_map_radar_path, resolve_visual_profile_file
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('inferno_builder', root/'scripts/rebuild_inferno_profile.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    radar = resolve_map_radar_path('de_inferno')
    regions = json.loads((radar.parent/'floor_regions.json').read_text())
    rebuilt = builder.build_mask(cv2.imread(str(radar)), regions)
    shipped = cv2.imread(str(resolve_visual_profile_file('de_inferno','walkable.png')),0)
    assert np.array_equal(rebuilt,shipped)
