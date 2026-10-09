"""Regression coverage for delayed atlas results and current-frame tracking."""
import importlib
import threading
from types import SimpleNamespace
import cv2
import numpy as np
import pytest


@pytest.fixture
def env(csgobot_module_path, monkeypatch):
    module = importlib.import_module('nav.async_perception')
    monkeypatch.setattr(module, 'read_grayscale', lambda _: np.zeros((1024,1024),np.uint8))
    monkeypatch.setattr(module, 'resolve_map_radar_path', lambda name: name)
    monkeypatch.setattr(module, 'observe_heading', lambda *_: (0., .95))
    class Reader:
        last_circle = (128,128,120)
        last_icon_xy = (128,128)
        last_icon_component = None
        valid = True
        def read(self,frame):
            return module.PoseResult(.5,.5,0.,.95,self.valid,40)
        def _crop_from_circle(self,frame,circle):
            return frame,128.,128.,120.
    entered, release = threading.Event(), threading.Event()
    class Scanner:
        def __init__(self,*_,**__): pass
        def register(self,*_):
            entered.set()
            release.wait(2)
            return SimpleNamespace(matrix=np.array([[1.,0.,100.],[0.,1.,100.]]),confidence=.95)
    monkeypatch.setattr(module, 'VisualLocalizer', Scanner)
    p = module.AsyncVisualPerception(Reader(),SimpleNamespace(map_id='test'))
    yield module,p,entered,release
    release.set()
    p.close()


def texture():
    rng=np.random.default_rng(812)
    gray=cv2.GaussianBlur(rng.integers(20,230,(256,256),dtype=np.uint8),(3,3),0)
    return cv2.cvtColor(gray,cv2.COLOR_GRAY2RGB)


def anchor(p, frame, stamp):
    matrix=np.array([[1.,0.,100.],[0.,1.,100.]])
    icon=p.reader.read(frame)
    p._result=(p._generation,stamp,frame,np.full((256,256),255,np.uint8),
               SimpleNamespace(matrix=matrix,confidence=.95),icon,(128,128),(0.,.95))


def test_slow_registration_does_not_block_control_or_survive_map_switch(env):
    _,p,entered,release=env
    frame=texture()
    assert not p.update(frame,now=1.).pose.valid
    assert entered.wait(1)
    # Worker remains blocked while current-frame processing and map reload run.
    assert not p.update(frame,now=1.1).pose.valid
    p.reload_map('test')
    release.set()
    p.close()
    assert p._result is None
    assert not p._thread.is_alive()


def test_fresh_pixels_track_fixed_anchor_without_chaining(env):
    _,p,_,_=env
    frame=texture();anchor(p,frame,1.)
    assert not p.update(frame,now=1.1).pose.valid
    result=p.update(frame,now=1.2).pose
    assert result.valid and result.observed_at==1.2
    assert abs(result.x_norm*1023-228)<1
    assert p._tracker.anchor[-1]==1.
    assert not p.update(np.zeros_like(frame),now=2.).pose.valid
    assert not p.update(frame,now=10.).pose.valid


def test_atlas_fallback_keeps_capture_time_and_expires(env,monkeypatch):
    _,p,_,_=env
    frame=texture()
    monkeypatch.setattr(p,'_current_registration',lambda *_:None)
    anchor(p,frame,1.)
    assert not p.update(frame,now=1.1).pose.valid
    anchor(p,frame,1.1)
    result=p.update(frame,now=1.2).pose
    assert result.valid and result.observed_at==1.1
    repeated=p.update(frame,now=1.3).pose
    assert repeated.valid and repeated.observed_at==1.1
    assert not p.update(frame,now=1.36).pose.valid


def test_missing_icon_discards_anchor_and_pending_generation(env):
    _,p,_,_=env
    frame=texture();anchor(p,frame,1.)
    p.update(frame,now=1.1);assert p.update(frame,now=1.2).pose.valid
    generation=p._generation
    p.reader.valid=False
    assert not p.update(frame,now=1.25).pose.valid
    assert p._result is None and p._tracker.anchor is None
    assert p._generation>generation
    p.reader.valid=True
    assert not p.update(frame,now=1.3).pose.valid


def test_circle_size_jitter_uses_same_tracking_coordinates(env):
    _,p,_,_=env
    frame=texture();anchor(p,frame,1.)
    def crop(current,circle):
        size=current.shape[0]
        p.reader.last_icon_xy=(size/2,size/2)
        return current,size/2,size/2,120*size/256
    p.reader._crop_from_circle=crop
    assert not p.update(cv2.resize(frame,(224,224)),now=1.1).pose.valid
    result=p.update(cv2.resize(frame,(226,226)),now=1.2).pose
    assert result.valid and result.observed_at==1.2
    assert abs(result.x_norm*1023-228)<1
    assert p._tracker.anchor[0].shape==(256,256)


def test_short_tracking_miss_never_extends_measured_deadline(env,monkeypatch):
    _,p,_,_=env
    frame=texture();anchor(p,frame,1.)
    p.update(frame,now=1.1);assert p.update(frame,now=1.2).pose.valid
    p._result=None
    monkeypatch.setattr(p,'_current_registration',lambda *_:None)
    result=p.update(frame,now=1.3).pose
    assert result.valid and result.observed_at==1.2
    assert not p.update(frame,now=1.46).pose.valid


def test_conflicting_registration_revokes_previous_anchor(env):
    _,p,_,_=env
    frame=texture();anchor(p,frame,1.)
    p.update(frame,now=1.1);assert p.update(frame,now=1.2).pose.valid
    p._result=None;p._rejected_at=1.25
    assert not p.update(frame,now=1.3).pose.valid
    assert p._accepted is None and p._tracker.anchor is None


def test_fast_global_contours_measure_current_frame_and_reset_on_map_change(env,monkeypatch):
    _,p,_,_=env
    frame=texture()
    monkeypatch.setattr(p,'_current_registration',lambda *_:None)
    p._dense_scale=.35
    matrix=np.array([[1.,0.,100.],[0.,1.,100.]])
    p._dense_fast=SimpleNamespace(match_at_scale=lambda *_:(matrix,.9,200))
    assert not p.update(frame,now=1.).pose.valid
    result=p.update(frame,now=1.1).pose
    assert result.valid and result.observed_at==1.1
    assert p.reason=='measured_global_contours'
    assert abs(result.x_norm*1023-228)<1
    p.reload_map('test')
    assert p._dense_scale is None and p._dense_fast is None
    assert not p.update(frame,now=1.2).pose.valid


def test_brief_heading_loss_keeps_only_original_pose_deadline(env,monkeypatch):
    module,p,_,_=env
    frame=texture();anchor(p,frame,1.)
    p.update(frame,now=1.1);assert p.update(frame,now=1.2).pose.valid
    monkeypatch.setattr(module,'observe_heading',lambda *_:None)
    result=p.update(frame,now=1.3).pose
    assert result.valid and result.observed_at==1.2
    assert not p.update(frame,now=1.46).pose.valid


def test_combat_observation_skips_slow_global_search(env,monkeypatch):
    _,p,entered,_=env
    monkeypatch.setattr(p,'_current_registration',lambda *_:None)
    p._dense_scale=.35
    def forbidden(*_):raise AssertionError('Global search on combat input loop')
    p._dense_fast=SimpleNamespace(match_at_scale=forbidden)
    p.update(texture(),now=1.,allow_global=False)
    assert entered.wait(1)


def test_inferno_fast_measurement_precedes_iterative_tracking(env, monkeypatch):
    _, p, _, _ = env
    p.map_id = 'de_inferno'
    p._dense_scale = .35
    p._dense_fast = SimpleNamespace(match_at_scale=lambda *args:
        (np.array([[1.,0.,100.],[0.,1.,100.]]), .95, 200))
    def unnecessary_tracker(*args, **kwargs):
        raise AssertionError('A fresh unique map match must skip iterative tracking')
    monkeypatch.setattr(p, '_current_registration', unnecessary_tracker)
    p.update(texture(), now=1.)
    assert p.update(texture(), now=1.1).pose.valid
    assert p.reason == 'measured_global_contours'


def test_inferno_combat_observation_requests_only_sparse_tracking(env, monkeypatch):
    _, p, _, _ = env
    p.map_id = 'de_inferno'
    modes = []
    def track(crop, mask, stamp, *, sparse_only=False):
        modes.append(sparse_only)
        return None
    monkeypatch.setattr(p, '_current_registration', track)
    p.update(texture(), now=1., allow_global=False)
    assert modes == [True]


def test_inferno_reload_has_zoom_hint_but_no_invented_pose(env, monkeypatch):
    _, p, _, _ = env
    p.reload_map('de_inferno')
    assert p._dense_scale == .355
    assert p._previous is None and p._accepted is None and p._result is None
    assert p.registration_status == 'starting'
    p._dense_fast = SimpleNamespace(match_at_scale=lambda *_:None)
    monkeypatch.setattr(p,'_current_registration',lambda *args,**kwargs:None)
    assert not p.update(texture(),now=1.).pose.valid
    p.reload_map('de_mirage')
    assert p._dense_scale == .355


def test_vertigo_global_frame_seeds_without_duplicate_worker_search(env):
    _,p,entered,_=env
    p.map_id='de_vertigo';p._dense_scale=.355
    p._dense_fast=SimpleNamespace(last_layer='upper',match_at_scale=lambda *_:(np.array([[1.,0,100],[0,1.,100]]),.95,100))
    frame=texture()
    assert not p.update(frame,now=1.).pose.valid
    assert p._seed_at==1. and p._seed_layer=='upper'
    assert p._job is None and not entered.is_set()
    assert p.update(frame,now=1.1).pose.valid
    anchor(p,frame,.5)  # completion of an older background job
    p._current_registration(frame,np.full((256,256),255,np.uint8),1.2)
    assert p._seed_at==1. and p._seed_layer=='upper'


def test_vertigo_new_floor_requires_two_current_observations(env):
    _,p,_,_=env
    p.map_id='de_vertigo';p._dense_scale=.355
    p._dense_fast=SimpleNamespace(last_layer='upper',match_at_scale=lambda *_:(np.array([[1.,0,100],[0,1.,100]]),.95,100))
    frame=texture();p.update(frame,now=1.)
    assert p.update(frame,now=1.1).pose.layer_id=='upper'
    p._dense_fast.last_layer='lower'
    assert not p.update(frame,now=1.2).pose.valid
    result=p.update(frame,now=1.3).pose
    assert result.valid and result.layer_id=='lower' and result.observed_at==1.3


def test_cache_global_frame_seeds_without_duplicate_worker_search(env):
    _,p,entered,_=env
    p.map_id='de_cache';p._dense_scale=.355
    p._dense_fast=SimpleNamespace(last_layer=None,match_at_scale=lambda *_:(np.array([[1.,0,100],[0,1.,100]]),.95,100))
    frame=texture()
    assert not p.update(frame,now=1.).pose.valid
    assert p._seed_at==1. and p._seed_layer is None
    assert p._job is None and not entered.is_set()
    assert p.update(frame,now=1.1).pose.valid
    anchor(p,frame,.5)  # completion of an older background job
    p._current_registration(frame,np.full((256,256),255,np.uint8),1.2)
    assert p._seed_at==1. and p._seed_layer is None


def test_mirage_global_frame_seeds_without_duplicate_worker_search(env):
    _,p,entered,_=env
    p.map_id='de_mirage';p._dense_scale=.355
    p._dense_fast=SimpleNamespace(last_layer=None,match_at_scale=lambda *_:(np.array([[1.,0,100],[0,1.,100]]),.95,100))
    frame=texture()
    assert not p.update(frame,now=1.).pose.valid
    assert p._seed_at==1. and p._seed_layer is None
    assert p._job is None and not entered.is_set()
    assert p.update(frame,now=1.1).pose.valid
    anchor(p,frame,.5)  # completion of an older background job
    p._current_registration(frame,np.full((256,256),255,np.uint8),1.2)
    assert p._seed_at==1. and p._seed_layer is None


def test_dust2_global_frame_seeds_without_duplicate_worker_search(env):
    _,p,entered,_=env
    p.map_id='de_dust2';p._dense_scale=.355
    p._dense_fast=SimpleNamespace(last_layer=None,match_at_scale=lambda *_:(np.array([[1.,0,100],[0,1.,100]]),.95,100))
    frame=texture()
    assert not p.update(frame,now=1.).pose.valid
    assert p._seed_at==1. and p._seed_layer is None
    assert p._job is None and not entered.is_set()
    assert p.update(frame,now=1.1).pose.valid
    anchor(p,frame,.5)  # completion of an older background job
    p._current_registration(frame,np.full((256,256),255,np.uint8),1.2)
    assert p._seed_at==1. and p._seed_layer is None


def test_dust2_hud_measurement_is_fresh_and_does_not_queue_worker(env):
    _,p,entered,_=env
    p.map_id='de_dust2';p._dense_scale=.355
    p._dense_fast=SimpleNamespace(match_at_scale=lambda *_:None)
    p._hud_fast=SimpleNamespace(match_at_scale=lambda *_:(np.array([[1.,0,100],[0,1.,100]]),.95,300))
    frame=texture()
    assert not p.update(frame,now=1.).pose.valid
    result=p.update(frame,now=1.1).pose
    assert result.valid and result.observed_at==1.1
    assert p.reason=='measured_hud_atlas_contours'
    assert p._job is None and not entered.is_set()
    p.reload_map('test')
    assert p._hud_fast is None



def test_heading_hint_is_current_and_disabled_on_spawn_or_missing_icon(env):
    _,p,_,_=env
    p.map_id='de_dust2';p._dense_scale=.355
    p._dense_fast=SimpleNamespace(match_at_scale=lambda *_:(np.array([[1.,0,100],[0,1.,100]]),.95,100))
    frame=texture()
    p.update(frame,now=1.)
    assert p.motion_hint is None  # Position confirmation must not continue an old spawn.
    p.update(frame,now=1.1)
    assert p.motion_hint.observed_at==1.1 and p.motion_hint.map_id=='de_dust2'
    p._dense_fast=SimpleNamespace(match_at_scale=lambda *_:(np.array([[1.,0,700],[0,1.,700]]),.95,100))
    assert not p.update(frame,now=1.2).pose.valid
    assert p.motion_hint is None
    p.reader.valid=False
    p.update(frame,now=1.3)
    assert p.motion_hint is None


def test_inferno_successful_fast_frame_does_not_start_duplicate_worker(env,monkeypatch):
    _,p,entered,_=env
    p.map_id='de_inferno';p._dense_scale=.35
    p._dense_fast=SimpleNamespace(match_at_scale=lambda *_:(np.array([[1.,0.,100.],[0.,1.,100.]]),.9,200))
    monkeypatch.setattr(p,'_current_registration',lambda *args,**kwargs:None)
    p.update(texture(),now=1.)
    assert not entered.wait(.05)
    assert p._tracker.anchor is not None
    assert p._seed_at==1.
