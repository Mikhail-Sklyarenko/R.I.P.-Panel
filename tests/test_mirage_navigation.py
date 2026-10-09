import importlib
import random
import pytest

@pytest.fixture
def nav(csgobot_module_path):
    return importlib.import_module('nav.farm_runtime')


def test_mirage_auto_pack_and_ground(nav):
    from nav.pack_resolve import measured_runtime_pack, nav_pack_for_script
    from nav.pack import load_nav_pack
    from nav.paths import resolve_nav_pack_path
    name = measured_runtime_pack(nav_pack_for_script('mirage', 'auto'), 'auto')
    assert name == 'mirage_visual'
    pack = load_nav_pack(resolve_nav_pack_path(name))
    ground = nav.load_ground(pack.map_id)
    assert ground is not None and ground.contains((.60, .46))
    assert not ground.contains((.55, .35))  # central building
    assert not ground.contains((.01, .01))
    assert measured_runtime_pack('dust2_dm', 'auto') == 'dust2_visual_mvp'


def test_map_selector_requires_unique_repeated_geometry(nav):
    from nav.map_selector import VisualMapSelector
    selector = VisualMapSelector.__new__(VisualMapSelector)
    selector.pending, selector.count = None, 0
    assert selector.confirm({'de_mirage': .82, 'de_dust2': .77}) is None
    assert selector.confirm({'de_mirage': .88, 'de_dust2': .3}) is None
    assert selector.confirm({'de_mirage': .89, 'de_dust2': .2}) is None
    assert selector.confirm({'de_mirage': .88, 'de_dust2': .1}) == 'de_mirage'
    assert selector.confirm({}) is None
    assert selector.confirm({'de_dust2': .9}) is None
    assert selector.confirm({'de_dust2': .9}) is None
    assert selector.confirm({'de_dust2': .9}) == 'de_dust2'


def test_mirage_roaming_from_scattered_positions(nav):
    import numpy as np
    from nav.roaming import RoamingGoals
    ground = nav.load_ground('de_mirage')
    roaming = RoamingGoals(ground, seed=17)
    ys, xs = np.nonzero(ground.grid)
    indices = random.Random(17).sample(range(len(xs)), 40)
    successful = 0
    for i in indices:
        origin = ground.norm((int(xs[i])*ground.step, int(ys[i])*ground.step))
        result = roaming.choose(origin)
        if result is None: continue
        goal, path = result
        assert all(ground.visible(a,b) for a,b in zip(path,path[1:]))
        successful += 1
    assert successful >= 35


def test_controller_switches_both_maps_without_old_position(nav):
    from nav.pack import load_nav_pack
    from nav.paths import resolve_nav_pack_path
    from types import SimpleNamespace
    owner = nav.CameraOwnership(lambda *args: None, lambda: True)
    controller = nav.create_navigation(load_nav_pack(resolve_nav_pack_path('dust2_visual_mvp')),
        SimpleNamespace(x360=7792), lambda key:None, lambda key:None, owner,
        expanded=True, watchdog=False)
    for name in ('mirage_visual','dust2_visual_mvp','mirage_visual'):
        pack = load_nav_pack(resolve_nav_pack_path(name))
        controller.reload_pack(pack)
        assert controller.last_pose is None
        assert controller.walkable is not None
        assert controller._roaming is not None
        assert not controller._obstacles
