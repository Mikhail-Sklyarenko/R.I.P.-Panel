"""Cache integration, random-spawn routing, and map-switch isolation."""
import importlib
import json
import random
import pytest
import numpy as np


@pytest.fixture
def nav(csgobot_module_path):
    return importlib.import_module('nav.farm_runtime')


def test_cache_auto_pack_and_preflight(nav):
    from nav.pack_resolve import measured_runtime_pack, nav_pack_for_script
    from nav.preflight import run_nav_preflight
    assert measured_runtime_pack(nav_pack_for_script('cache'), 'auto') == 'cache_visual'
    result = run_nav_preflight(pack_id='auto')
    assert result['ok'], result['errors']
    assert 'cache_visual' in result['packs_ok']
    from map.parse import parse_map_script
    for text in ('Deathmatch | Cache', 'de_cache', 'CACHE'):
        assert parse_map_script(text) == 'cache'
    assert parse_map_script('UnsupportedMap') is None


def test_cache_confirmation_and_three_map_switch(nav):
    from nav.map_confirmation import active_map_confirmed, named_match_ready
    from nav.map_selector import VisualMapSelector
    from map.hud_map_detect import MapDetectState, update_map_hysteresis
    state = MapDetectState.from_script('dust2')
    for script in ('cache', 'vertigo', 'inferno', 'mirage', 'dust2', 'cache'):
        for _ in range(3):
            update_map_hysteresis(state, script, confirm_frames=3, lock_after_confirm=True)
        assert active_map_confirmed('de_' + script, state)
        assert named_match_ready(script, 'match_ready')
        assert not named_match_ready(script, 'scoreboard')
    selector = VisualMapSelector.__new__(VisualMapSelector)
    selector.pending, selector.count = None, 0
    for _ in range(3):
        assert selector.confirm({'de_cache': .85, 'de_dust2': .81}) is None
    assert selector.confirm({'de_cache': .9, 'de_mirage': .3}) is None
    assert selector.confirm({'de_cache': .9, 'de_mirage': .3}) is None
    assert selector.confirm({'de_cache': .9, 'de_mirage': .3}) == 'de_cache'


def test_cache_floor_connects_major_areas_without_cutting_walls(nav):
    ground = nav.load_ground('de_cache')
    assert ground is not None and ground.step == 2
    points = [(900,610),(750,725),(480,770),(490,833),(355,830),
              (350,750),(200,630),(100,560),(195,370),(305,265),
              (420,300),(485,380),(570,325),(590,465),(610,570),(415,530)]
    for point in points:
        origin = ground.norm(point)
        assert ground.contains(origin), point
        path = ground.plan(origin, ground.norm((415,530)))
        assert path, point
        assert all(ground.visible(a,b) for a,b in zip(path,path[1:]))
    for blocked in ((20,20),(600,690),(580,540),(350,280),(420,600),(490,700),(280,710),(450,275)):
        assert not ground.contains(ground.norm(blocked))


def test_cache_scattered_spawn_roaming(nav):
    from nav.roaming import RoamingGoals
    ground = nav.load_ground('de_cache')
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


def test_cache_reloads_without_previous_map_pose(nav):
    from nav.pack import load_nav_pack
    from nav.paths import resolve_nav_pack_path
    from types import SimpleNamespace
    owner = nav.CameraOwnership(lambda *args: None, lambda: True)
    controller = nav.create_navigation(load_nav_pack(resolve_nav_pack_path('dust2_visual_mvp')),
        SimpleNamespace(x360=7792), lambda key:None, lambda key:None, owner,
        expanded=True, watchdog=False)
    for name in ('cache_visual','vertigo_visual','inferno_visual','mirage_visual','dust2_visual_mvp','cache_visual'):
        controller.reload_pack(load_nav_pack(resolve_nav_pack_path(name)))
        assert controller.last_pose is None
        assert controller.walkable is not None
        assert controller._roaming is not None
        assert not controller._obstacles


def test_cache_atlas_has_distributed_calibration_and_explicit_limits(nav):
    from nav.paths import resolve_visual_profile_file
    p = resolve_visual_profile_file('de_cache','atlas.json')
    atlas = json.loads(p.read_text())
    centers = []
    for ref in atlas['references']:
        assert (p.parent / ref['image']).is_file()
        matrix = np.array(ref['to_map'])
        assert matrix.shape == (2,3) and np.isfinite(matrix).all()
        centers.append(matrix @ [112,112,1])
    assert np.ptp(centers,axis=0).min() > 550
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


def test_cache_mask_rebuild_matches_shipped_asset(nav):
    import cv2
    import importlib.util
    from pathlib import Path
    from nav.paths import resolve_map_radar_path, resolve_visual_profile_file
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('cache_builder', root/'scripts/rebuild_cache_profile.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    radar = resolve_map_radar_path('de_cache')
    regions = json.loads((radar.parent/'floor_regions.json').read_text())
    rebuilt = builder.build_mask(cv2.imread(str(radar)), regions)
    shipped = cv2.imread(str(resolve_visual_profile_file('de_cache','walkable.png')),0)
    assert np.array_equal(rebuilt,shipped)


def test_cache_radar_uses_visible_alpha_only(nav):
    import cv2
    from nav.paths import resolve_map_radar_path
    p = resolve_map_radar_path('de_cache')
    raw = cv2.imread(str(p.parent/'source_radar.png'),cv2.IMREAD_UNCHANGED)
    radar = cv2.imread(str(p))
    assert raw.shape[2] == 4
    assert np.array_equal(radar,np.uint8(raw[:,:,:3].astype(float)*(raw[:,:,3:4]/255)))
    assert not radar[raw[:,:,3]==0].any()


@pytest.mark.parametrize('stamp',[9,45,137,177])
def test_cache_localizes_uncalibrated_recording_frames(nav,stamp):
    import cv2
    from pathlib import Path
    from nav.visual_localizer import VisualLocalizer
    root=Path(__file__).parent/'fixtures/nav_cache'
    rgb=cv2.cvtColor(cv2.imread(str(root/f'{stamp}.png')),cv2.COLOR_BGR2RGB)
    mask=cv2.imread(str(root/f'{stamp}_mask.png'),0)
    ref=json.loads((root/'expected.json').read_text())[str(stamp)]
    result=VisualLocalizer('de_cache').register(rgb,mask)
    assert result is not None and result.confidence>=.72
    assert np.linalg.norm((result.matrix-np.array(ref))@np.array([112,112,1]))<8


def test_cache_rejects_other_four_maps(nav):
    import cv2
    from nav.visual_localizer import VisualLocalizer
    from nav.paths import resolve_visual_profile_file
    localizer=VisualLocalizer('de_cache')
    for mid in ('de_dust2','de_mirage','de_inferno','de_vertigo','de_vertigo_lower'):
        path=resolve_visual_profile_file(mid,'atlas.json')
        refs=json.loads(path.read_text())['references']
        for ref in refs[::max(1,len(refs)//3)][:3]:
            rgb=cv2.cvtColor(cv2.imread(str(path.parent/ref['image'])),cv2.COLOR_BGR2RGB)
            mask=np.uint8(np.any(rgb>8,axis=2))*255
            result=localizer.register(rgb,mask)
            assert result is None or result.confidence<.72,(mid,ref['image'],result)
