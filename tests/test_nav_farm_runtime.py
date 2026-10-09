import importlib
import threading
import pytest

@pytest.fixture
def runtime(csgobot_module_path):
    return importlib.import_module('nav.farm_runtime')


def test_ownership_blocks_nav_during_aim_and_releases_after_combat(runtime):
    output=[];allowed=[True]
    gate=runtime.CameraOwnership(lambda dx,dy:output.append((dx,dy)),lambda:allowed[0])
    gate.select('nav');gate.emit('nav',1,0);gate.emit('combat',2,0)
    gate.select('combat');gate.emit('nav',3,0);gate.emit('combat',4,0)
    allowed[0]=False;gate.emit('combat',5,0);gate.emit('nav',6,0)
    allowed[0]=True;gate.select('nav');gate.emit('combat',7,0);gate.emit('nav',8,0)
    assert output==[(1,0),(4,0),(8,0)]


def test_ownership_change_waits_for_inflight_delta(runtime):
    inside=threading.Event();release=threading.Event();switched=threading.Event();output=[]
    def move(dx,dy):
        inside.set();assert release.wait(2);output.append(dx)
    gate=runtime.CameraOwnership(move,lambda:True);gate.select('nav')
    writer=threading.Thread(target=lambda:gate.emit('nav',1,0));writer.start();assert inside.wait(2)
    changer=threading.Thread(target=lambda:(gate.select('combat'),switched.set()));changer.start()
    assert not switched.wait(.02)
    release.set();writer.join(2);changer.join(2)
    gate.emit('nav',2,0)
    assert switched.is_set() and output==[1]


def test_mode_is_explicit_and_profile_is_expanded(runtime,monkeypatch):
    monkeypatch.delenv('CSGOBOT_NAV_MODE',raising=False);assert not runtime.expanded_mode()
    monkeypatch.setenv('CSGOBOT_NAV_MODE','expanded_roam');assert runtime.expanded_mode()
    ground=runtime.load_ground('de_dust2')
    assert ground.contains((.4,.9)) and not ground.contains((.01,.01))


def test_missing_expanded_profile_fails_closed(runtime,monkeypatch,tmp_path):
    monkeypatch.setattr(runtime,'resolve_nav_root',lambda:tmp_path)
    with pytest.raises(ValueError,match='profile missing'):runtime.load_ground('de_dust2')


def test_real_controller_yields_keys_and_mouse_to_combat(runtime):
    from nav.pack import load_nav_pack
    from nav.paths import resolve_nav_pack_path
    from nav.pose import PoseResult
    from types import SimpleNamespace
    import time
    held=set();output=[]
    owner=runtime.CameraOwnership(lambda x,y:output.append(x),lambda:True)
    ctrl=runtime.create_navigation(load_nav_pack(resolve_nav_pack_path('dust2_visual_mvp')),
        SimpleNamespace(fov=SimpleNamespace(x360=3600)),held.add,held.discard,owner,expanded=True,watchdog=False)
    try:
        owner.select('nav')
        for _ in range(3):
            stamp=time.monotonic()
            ctrl.tick(PoseResult(.4,.9,0,.9,True,20,'visual',None,stamp),now=stamp,paused=False)
        assert ctrl.goal_id.startswith('roam_') and ctrl.walkable.contains((.4,.9))
        owner.select('combat')
        before=len(output)
        stamp=time.monotonic()
        ctrl.tick(PoseResult(.4,.9,0,.9,True,20,'visual',None,stamp),now=stamp,paused=False)
        assert not held and len(output)==before
        owner.emit('combat',9,0);assert output[-1]==9
    finally:ctrl.close()


def test_map_reload_uses_new_profile_not_previous_dust2_mask(runtime,monkeypatch):
    from nav.walkable import WalkableMap
    from nav.pack import load_nav_pack
    from nav.paths import resolve_nav_pack_path
    from types import SimpleNamespace
    from dataclasses import replace
    import numpy as np
    calls=[]
    def loader(map_id):
        calls.append(map_id)
        return WalkableMap(np.full((100,100),255,np.uint8),clearance_px=2) if map_id=='de_dust2' else None
    monkeypatch.setattr(runtime,'load_ground',loader)
    pack=load_nav_pack(resolve_nav_pack_path('dust2_visual_mvp'))
    ctrl=runtime.create_navigation(pack,SimpleNamespace(fov=SimpleNamespace(x360=3600)),lambda k:None,lambda k:None,runtime.CameraOwnership(lambda *a:None,lambda:True),expanded=True,watchdog=False)
    try:
        assert ctrl.walkable is not None
        ctrl.reload_pack(replace(pack,map_id='de_unknown'))
        assert ctrl.walkable is None and calls==['de_dust2','de_unknown']
    finally:ctrl.close()


def test_detector_imread_patch_does_not_break_ground(runtime, monkeypatch):
    import cv2
    import numpy as np
    expected = runtime.load_ground('de_dust2').free.copy()
    original = cv2.imread

    def detector_imread(path, flags=cv2.IMREAD_COLOR):
        image = original(path, flags)
        if image is not None and image.ndim == 2:
            return image[..., None]
        return image

    monkeypatch.setattr(cv2, 'imread', detector_imread)
    actual = runtime.load_ground('de_dust2')
    assert actual.free.ndim == 2
    np.testing.assert_array_equal(actual.free, expected)


@pytest.mark.parametrize('payload', [b'', b'not a png'])
def test_invalid_navigation_image_rejected(runtime, tmp_path, payload):
    from nav.walkable import read_grayscale
    path = tmp_path / 'walkable.png'
    path.write_bytes(payload)
    with pytest.raises(ValueError, match='navigation image'):
        read_grayscale(path)
