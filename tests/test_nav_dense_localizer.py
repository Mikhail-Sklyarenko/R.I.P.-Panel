import importlib
import cv2
import numpy as np
import pytest


@pytest.fixture
def matcher_type(csgobot_module_path):
    return importlib.import_module('nav.dense_localizer').DenseMapMatcher


def ground(seed=18):
    rng=np.random.default_rng(seed)
    rgb=np.full((1024,1024,3),20,np.uint8)
    for _ in range(180):
        x,y=rng.integers(10,930,2);w,h=rng.integers(12,90,2)
        v=int(rng.integers(70,190))
        cv2.rectangle(rgb,(x,y),(x+w,y+h),(v,v,v),-1)
    return rgb


def view(rgb,x=270.,y=300.,size=200):
    matrix=np.array([[1/.35,0.,x],[0.,1/.35,y]])
    crop=cv2.warpAffine(rgb,matrix,(size,size),flags=cv2.INTER_LINEAR|cv2.WARP_INVERSE_MAP)
    yy,xx=np.ogrid[:size,:size];d=(xx-size/2)**2+(yy-size/2)**2
    mask=np.uint8((d<(size/2-8)**2)&(d>20**2))*255
    return crop,mask,matrix


def test_global_contours_recover_known_position_with_background_tint(matcher_type):
    rgb=ground();crop,mask,expected=view(rgb)
    tinted=np.uint8(np.clip(crop*.7+np.array([55,30,10]),0,255))
    result=matcher_type(rgb).match(tinted,mask)
    assert result is not None
    matrix,confidence,_=result
    assert np.linalg.norm((matrix-expected)@np.array([100,100,1]))<4
    assert confidence>=.70


def test_unrelated_and_blank_images_are_not_map_coordinates(matcher_type):
    rgb=ground();matcher=matcher_type(rgb)
    crop,mask,_=view(ground(77))
    assert matcher.match(crop,mask) is None
    assert matcher.match(np.zeros_like(crop),mask) is None
    noise=np.random.default_rng(9).integers(0,255,crop.shape,dtype=np.uint8)
    assert matcher.match(noise,mask) is None


def test_repeated_map_regions_are_rejected_as_ambiguous(matcher_type):
    rgb=ground();rgb[:,512:]=rgb[:,:512]
    crop,mask,_=view(rgb,20.,200.,160)
    assert matcher_type(rgb).match(crop,mask) is None


def test_cached_zoom_still_searches_new_spawns_globally(matcher_type):
    rgb=ground();matcher=matcher_type(rgb)
    crop,mask,_=view(rgb)
    assert matcher.match(crop,mask) is not None
    crop,mask,expected=view(rgb,30.,80.)
    result=matcher.match(crop,mask)
    assert result is not None
    assert np.linalg.norm((result[0]-expected)@np.array([100,100,1]))<4


def test_translucent_mode_still_rejects_unrelated_and_repeated_geometry(matcher_type):
    rgb = ground()
    matcher = matcher_type(rgb, translucent=True)
    crop, mask, _ = view(ground(77))
    assert matcher.match(crop, mask) is None
    assert matcher.match(np.zeros_like(crop), mask) is None
    rgb[:,512:] = rgb[:,:512]
    crop, mask, _ = view(rgb,20.,200.,160)
    assert matcher_type(rgb, translucent=True).match(crop,mask) is None


@pytest.mark.parametrize('stamp,origin', [(30,(310.,606.)), (140,(631.,217.))])
def test_inferno_boundary_strip_has_unique_measurable_position(matcher_type, stamp, origin):
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    fixture = root/'tests/fixtures/nav_inferno_boundary'
    rgb = cv2.cvtColor(cv2.imread(str(root/'resources/nav/maps/de_inferno/radar.png')),cv2.COLOR_BGR2RGB)
    crop = cv2.cvtColor(cv2.imread(str(fixture/f'{stamp}.png')),cv2.COLOR_BGR2RGB)
    mask = cv2.imread(str(fixture/f'{stamp}_mask.png'),cv2.IMREAD_GRAYSCALE)
    # The broad-disk gate previously rejected both real HUD frames forever.
    assert matcher_type(rgb).match_at_scale(crop,mask,.355) is None
    result = matcher_type(rgb,translucent=True).match_at_scale(crop,mask,.355)
    assert result is not None
    expected = np.array([[1/.355,0,origin[0]],[0,1/.355,origin[1]]])
    assert np.linalg.norm((result[0]-expected)@np.array([112,112,1])) < 3
    # The very same partial geometry must not become a location on other maps.
    for map_id in ('de_dust2','de_mirage'):
        other = cv2.cvtColor(cv2.imread(str(root/f'resources/nav/maps/{map_id}/radar.png')),cv2.COLOR_BGR2RGB)
        assert matcher_type(other,translucent=True).match(crop,mask) is None


def test_translucent_single_wall_is_not_enough_for_a_position(matcher_type):
    rgb = np.full((1024,1024,3),20,np.uint8)
    cv2.rectangle(rgb,(120,400),(920,430),(140,140,140),-1)
    crop,mask,_ = view(rgb,270.,300.)
    assert matcher_type(rgb,translucent=True).match(crop,mask) is None
