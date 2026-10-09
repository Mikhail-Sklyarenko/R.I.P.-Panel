"""Floor separation, current-pixel confirmation and integrated four-map routing."""
import importlib
import json
from types import SimpleNamespace
import cv2
import numpy as np
import pytest


@pytest.fixture
def nav(csgobot_module_path):
    return importlib.import_module('nav.farm_runtime')


def test_four_map_selection_and_vertigo_preflight(nav):
    from nav.pack_resolve import nav_pack_for_script
    from nav.preflight import run_nav_preflight
    from map.parse import parse_map_script
    from map.hud_map_detect import MapDetectState,update_map_hysteresis
    from nav.map_confirmation import active_map_confirmed
    for text in ('Vertigo','DE_VERTIGO','Бой насмерть | Vertigo'):
        assert parse_map_script(text) == 'vertigo'
    state=MapDetectState.from_script('dust2')
    for script in ('vertigo','inferno','mirage','dust2','vertigo'):
        for _ in range(3):update_map_hysteresis(state,script,confirm_frames=3,lock_after_confirm=True)
        assert active_map_confirmed('de_'+script,state)
    assert nav_pack_for_script('vertigo') == 'vertigo_visual'
    result=run_nav_preflight(pack_id='auto')
    assert result['ok'],result['errors']
    assert 'vertigo_visual' in result['packs_ok']


def test_portals_are_walkable_in_both_directions_without_union_of_floors(nav):
    from nav.walkable import WalkableMap
    from nav.paths import resolve_visual_profile_file
    from nav.layered_roaming import LayeredRoamingGoals
    cfg=json.loads(resolve_visual_profile_file('de_vertigo','layers.json').read_text())
    upper,lower=WalkableMap.load('de_vertigo'),WalkableMap.load('de_vertigo_lower')
    assert upper.contains(upper.norm((500,400)))
    assert not lower.contains(lower.norm((500,400)))
    assert lower.contains(lower.norm((400,770)))
    assert not upper.contains(upper.norm((400,770)))
    for level,ground,origin in [('upper',upper,(500,400)),('lower',lower,(400,770))]:
        for portal in cfg['portals']:
            route=[ground.norm(p) for p in portal['upper_to_lower']]
            assert all(ground.visible(a,b) and ground.visible(b,a) for a,b in zip(route,route[1:]))
            assert ground.plan(ground.norm(origin),route[0])
        roaming=LayeredRoamingGoals(ground,level,cfg['portals'],seed=1)
        goal,path=roaming.choose(ground.norm(origin),now=40.)
        assert goal.id.startswith('portal_')
        assert all(ground.visible(a,b) for a,b in zip(path,path[1:]))
        assert not ground.contains(ground.norm((478,625)))  # ladder shaft


def test_floor_change_discards_old_route_obstacles_and_keys(nav):
    from nav.pack import load_nav_pack
    from nav.paths import resolve_nav_pack_path
    from nav.pose import PoseResult
    owner=nav.CameraOwnership(lambda *a:None,lambda:True);owner.select('nav')
    controller=nav.create_navigation(load_nav_pack(resolve_nav_pack_path('vertigo_visual')),
        SimpleNamespace(x360=7792),lambda key:None,lambda key:None,owner,expanded=True,watchdog=False)
    try:
        pose=PoseResult(.49,.39,0.,.9,True,radar_mode='visual',observed_at=1.,layer_id='upper')
        controller.tick(pose,now=1.,paused=False)
        controller._path=((.1,.1),(.2,.2));controller._history.append((.1,.1))
        controller._set_keys({'w'});old_ground=controller.walkable
        changed=PoseResult(.4,.75,0.,.9,True,radar_mode='visual',observed_at=1.1,layer_id='lower')
        controller.tick(changed,now=1.1,paused=False)
        assert controller._active_layer == 'lower' and controller.walkable is not old_ground
        assert not controller._history and not controller._path and not controller._keys
        missing=PoseResult(.4,.75,0.,.9,True,radar_mode='visual',observed_at=1.2)
        controller.tick(missing,now=1.2,paused=False)
        assert controller.reason == 'unconfirmed_floor' and not controller._keys
    finally:controller.close()


def test_same_xy_different_floor_is_not_resolved_by_confidence_alone(nav):
    from nav.layered_localizer import select_layer
    from nav.visual_localizer import Registration
    rng=np.random.default_rng(5);rgb=rng.integers(30,120,(180,180,3),dtype=np.uint8)
    mask=np.full((180,180),255,np.uint8);matrix=np.array([[1.,0,0],[0,1.,0]])
    candidates={'upper':Registration(matrix,.99,30,0.,'atlas'),'lower':Registration(matrix,.72,20,0.,'atlas')}
    assert select_layer(rgb,mask,candidates,{'upper':rgb,'lower':rgb}) is None
    lower=np.uint8(150-rgb)
    result=select_layer(rgb,mask,candidates,{'upper':rgb,'lower':lower})
    assert result is not None and result.layer_id == 'upper'
    moved=Registration(matrix+np.array([[0,0,100],[0,0,0]]),.9,20,0.,'atlas')
    assert select_layer(rgb,mask,{'upper':candidates['upper'],'lower':moved},{'upper':rgb,'lower':lower}).layer_id == 'upper'


def test_random_spawn_goals_on_each_floor(nav):
    from nav.walkable import WalkableMap
    from nav.roaming import RoamingGoals
    import random
    for mid in ('de_vertigo','de_vertigo_lower'):
        ground=WalkableMap.load(mid);roaming=RoamingGoals(ground,seed=7)
        ys,xs=np.nonzero(ground.grid);success=0
        for i in random.Random(7).sample(range(len(xs)),24):
            result=roaming.choose(ground.norm((int(xs[i])*ground.step,int(ys[i])*ground.step)))
            if result:
                _,path=result;assert all(ground.visible(a,b) for a,b in zip(path,path[1:]));success+=1
        assert success>=22


def test_radar_alpha_and_masks_rebuild_exactly(nav):
    import importlib.util
    from pathlib import Path
    from nav.paths import resolve_nav_root
    root=resolve_nav_root().parents[1]
    spec=importlib.util.spec_from_file_location('vertigo_builder',root/'scripts/rebuild_vertigo_profile.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    pixel=np.array([[[104,111,112,0],[80,60,40,255]]],np.uint8)
    composite=builder.composite_radar(pixel)
    assert not composite[0,0].any() and np.array_equal(composite[0,1],pixel[0,1,:3])
    cfg=json.loads((resolve_nav_root()/'profiles/de_vertigo/layers.json').read_text())
    for layer,mid in cfg['layers'].items():
        folder=resolve_nav_root()/'maps'/mid
        radar=builder.composite_radar(cv2.imread(str(folder/'source_radar.png'),cv2.IMREAD_UNCHANGED))
        assert np.array_equal(radar,cv2.imread(str(folder/'radar.png')))
        mask=builder.build_mask(radar,layer,cfg['portals'],cfg.get('geometry_edits',()))
        assert np.array_equal(mask,cv2.imread(str(resolve_nav_root()/'profiles'/mid/'walkable.png'),0))


@pytest.mark.parametrize('stamp,layer',[(77,'upper'),(109,'lower')])
def test_current_hud_combines_geometry_and_floor_appearance(nav,stamp,layer):
    from nav.layered_localizer import LayeredDenseMatcher
    from nav.paths import resolve_nav_root
    from pathlib import Path
    root=resolve_nav_root().parents[1]
    fixture=root/'tests/fixtures/nav_vertigo'
    crop=cv2.cvtColor(cv2.imread(str(fixture/f'{stamp}.png')),cv2.COLOR_BGR2RGB)
    mask=cv2.imread(str(fixture/f'{stamp}_mask.png'),0)
    radar=cv2.cvtColor(cv2.imread(str(resolve_nav_root()/'maps/de_vertigo/radar.png')),cv2.COLOR_BGR2RGB)
    matcher=LayeredDenseMatcher(radar)
    result=matcher.match_at_scale(crop,mask,.355)
    assert result is not None and matcher.last_layer==layer and result[1]>=.72
    assert matcher.match_at_scale(np.zeros_like(crop),mask,.355) is None
    assert matcher.last_layer is None
    noise=np.random.default_rng(11).integers(0,255,crop.shape,dtype=np.uint8)
    assert matcher.match_at_scale(noise,mask,.355) is None


def test_other_map_hud_images_do_not_become_vertigo_floors(nav):
    from nav.layered_localizer import LayeredDenseMatcher
    from nav.paths import resolve_nav_root
    radar=cv2.cvtColor(cv2.imread(str(resolve_nav_root()/'maps/de_vertigo/radar.png')),cv2.COLOR_BGR2RGB)
    matcher=LayeredDenseMatcher(radar)
    for mid in ('de_dust2','de_mirage','de_inferno'):
        directory=resolve_nav_root()/'profiles'/mid
        refs=json.loads((directory/'atlas.json').read_text())['references']
        for ref in refs[::max(1,len(refs)//4)][:4]:
            crop=cv2.cvtColor(cv2.imread(str(directory/ref['image'])),cv2.COLOR_BGR2RGB)
            mask=np.uint8(np.any(crop>8,axis=2))*255
            assert matcher.match_at_scale(crop,mask,.355) is None, (mid,ref['image'])
